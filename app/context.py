from __future__ import annotations

"""Context builder: assembles prompt blocks within a token budget.

Anti-hallucination strategies from README §4:
  - system prompt ≤ 1/3 of context window
  - injectable blocks (ls tree, rules, RAG) delivered as TAIL messages (KV-cache preservation)
  - deduplication: byte-identical block not re-injected
"""

import json
import os
from pathlib import Path
from typing import Any

from tools.guards.state import estimate_tokens

MAX_LS_TOKENS = 500
MAX_RULES_TOKENS = 400
MAX_SUMMARY_TOKENS = 500
MIN_TAIL_TOKENS = 256


class ContextBuilder:
    def __init__(self, cwd: str, context_window: int, config: dict[str, Any] | None = None):
        self.cwd = cwd
        self.context_window = context_window
        self.config = config or {}
        self._last_blocks: dict[str, str] = {}

    # ------------------------------------------------------------------ helpers
    def _ls_tree(self) -> str:
        max_lines = 60
        lines = []
        try:
            for p in sorted(Path(self.cwd).iterdir()):
                name = p.name
                if name.startswith("."):
                    continue  # hidden artifacts (.tiny-agent, .git) are NOT visible to the model
                if name in ("node_modules", "__pycache__", ".venv", "venv"):
                    continue
                if p.is_dir():
                    lines.append(f"{name}/")
                else:
                    lines.append(name)
                if len(lines) >= max_lines:
                    lines.append("... (truncated)")
                    break
        except OSError:
            pass
        return "Project root files:\n" + "\n".join(lines)

    def _sdds(self) -> str:
        parts = []
        for name in ("ARCHITECTURE.md", "TASKS.md", "STORIES.md", "RULES.md"):
            p = Path(self.cwd) / name
            if p.exists():
                try:
                    text = p.read_text(encoding="utf-8")[:1200]
                    parts.append(f"### {name}\n{text}")
                except OSError:
                    pass
        if not parts:
            return ""
        return "\n\n".join(parts[:2])

    def _rules(self) -> str:
        rules_dir = Path(self.cwd) / ".tiny-agent" / "rules"
        parts = []
        if rules_dir.exists():
            for p in sorted(rules_dir.glob("*.md"))[:5]:
                try:
                    parts.append(p.read_text(encoding="utf-8")[:500])
                except OSError:
                    pass
        if not parts:
            return ""
        return "Rules (from LLM-as-judge, must be followed):\n" + "\n---\n".join(parts)

    def _todo(self, todo: dict | None) -> str:
        if not todo:
            return ""
        parts = [f"Todo status: {todo.get('status', 'pending')}"]
        if todo.get("description"):
            parts.append(f"Task: {todo['description'][:200]}")
        for t in (todo.get("completed") or [])[-5:]:
            parts.append(f"  [x] {t}")
        return "\n".join(parts)

    # ------------------------------------------------------------------ build
    def build(
        self,
        system_prompt: str,
        user_prompt: str,
        history: list[dict[str, Any]] | None = None,
        todo: dict | None = None,
        summary: str | None = None,
        extra: list[tuple[str, str]] | None = None,
    ) -> list[dict[str, Any]]:
        """Returns OpenAI messages array. Tail blocks injected as user messages."""
        # 1. system prompt
        sys_tokens = estimate_tokens(system_prompt)
        budget = max(MIN_TAIL_TOKENS, self.context_window // 3)
        if sys_tokens > self.context_window // 3:
            system_prompt = system_prompt[: (self.context_window // 3) * 3]
            sys_tokens = estimate_tokens(system_prompt)

        messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
        messages.extend(history or [])

        # 2. tail blocks (KV-cache: appended at the end, byte-dedup)
        blocks: list[tuple[str, str]] = []
        blocks.append(("ls", self._ls_tree()))
        sdd = self._sdds()
        if sdd:
            blocks.append(("sdd", sdd))
        rules = self._rules()
        if rules:
            blocks.append(("rules", rules))
        todo_b = self._todo(todo)
        if todo_b:
            blocks.append(("todo", todo_b))
        if summary:
            blocks.append(("summary", f"Summary of previous work:\n{summary[: MAX_SUMMARY_TOKENS * 3]}"))
        if extra:
            blocks.extend(extra)

        tail = ""
        for key, content in blocks:
            if not content:
                continue
            if self._last_blocks.get(key) == content:
                continue  # dedup — already in context
            self._last_blocks[key] = content
            tail += f"\n\n{content}" if tail else content
            if estimate_tokens(tail) > budget:
                tail = tail[: budget * 3]
                break

        messages.append({"role": "user", "content": user_prompt})
        if tail:
            messages.append({"role": "user", "content": tail})
        return messages

    def build_summary_prompt(self, history: list[dict[str, Any]]) -> str:
        """Strip technical noise (tool logs, truncation markers) so the 0.8b summarizer
        doesn't hallucinate about the task from tool metadata."""
        clean = []
        for m in history[-30:]:
            content = m.get("content", "")
            if isinstance(content, str):
                if content.startswith("Tool result") and len(content) > 800:
                    content = content[:500] + "\n...[truncated]"
                if content.startswith("[guard]") or content.startswith("[tool-error]"):
                    continue
                if "Tool:" in content and content.index("Tool:") == 0:
                    content = "(tool call executed)"
            clean.append({"role": m.get("role"), "content": content})
        return (
            "Summarize this coding-agent conversation into a task-state summary (max 250 words). "
            "Include ONLY: the original task, files created/edited, current state, and the single next step. "
            "Do NOT mention tool names as if they were part of the task.\n\n"
            + json.dumps(clean, ensure_ascii=False, default=str)[:7000]
        )

    def compact_messages(self, history: list[dict[str, Any]], summary: str) -> list[dict[str, Any]]:
        return [{"role": "system", "content": summary}]

    def reset_dedup(self) -> None:
        self._last_blocks = {}
