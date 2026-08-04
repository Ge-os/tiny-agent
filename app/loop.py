from __future__ import annotations

"""Main agent loop with anti-hallucination strategies.

Strategies (README §5, §2, §4):
  - repeat-guard: identical successful tool call is blocked → model must answer
  - nudge-to-answer: after every tool result the model is pushed to respond in text
  - loop detection: 3 identical calls → LLM summary + fresh chat
  - code-in-chat detection → offer write to file
  - deterministic tool correction (tools/correction.py) after failed calls
  - sub-agent corrector (app/subagent.py) for invalid calls, with RAG docs
  - guard results fed back to the model with corrections
"""

import json
import os
import time
from typing import Any, Callable

from app.api import ApiClient, CorrectedCall, ModelResponse, ToolCallRecovery
from app.context import ContextBuilder
from app.judge import Judge
from app.prompts.roles import get_agent, render
from app.rag import Rag
from app.subagent import ToolCorrector
from tools.base import ToolResult
from tools.correction import correct_call
from tools.file_tools import _dedupe_md_tasks as _dedupe_doc_tasks
from tools.guards.state import SessionState, estimate_tokens

MAX_TURNS_DEFAULT = 30
MAX_SUMMARY_TOKENS = 500
ANSWER_NUDGE = (
    "You have the tool result above. Now apply the next step of the task "
    "(edit the file if needed), then answer the user in plain text."
)
FINAL_NUDGE = (
    "The change is applied. Now answer the user in plain text with a short summary of what was done."
)


class LoopDetected(Exception):
    pass


class AgentLoop:
    def __init__(
        self,
        client: ApiClient,
        registry,
        context_builder: ContextBuilder,
        state: SessionState,
        cwd: str,
        agent_name: str = "coder",
        max_turns: int = MAX_TURNS_DEFAULT,
        confirm_callback: Callable[[str, str], str] | None = None,
        log_callback: Callable[[str, str], None] | None = None,
        rag: Rag | None = None,
        judge: Judge | None = None,
    ):
        self.client = client
        self.registry = registry
        self.ctx = context_builder
        self.state = state
        self.cwd = cwd
        self.agent_name = agent_name
        self.spec = get_agent(agent_name)
        self.allowed_tools = self.spec.tools or registry.names()
        self.max_turns = max_turns
        self.confirm_callback = confirm_callback
        self.log_callback = log_callback
        self.rag = rag or Rag()
        self.judge = judge
        self.corrector = ToolCorrector(client, registry, self.rag)
        self.recovery = ToolCallRecovery(registry)
        self.history: list[dict[str, Any]] = []
        self.todo: dict | None = None
        self.summary: str | None = None
        self.last_result: str | None = None
        self._consecutive_corrections = 0
        self._blocked_after_edit = 0
        self._edit_done = False
        self._corrections_injected = 0
        self._stuck_reads = 0
        self._deliverable_tried = False
        self._failed_reads: dict[str, int] = {}
        self._last_text: str | None = None
        self._text_repeats = 0
        self._task_prompt = ""
        self._last_subagent_proposal: str | None = None
        self._subagent_repeats = 0
        # tiny models degrade in long contexts: compact aggressively (default 4096 tokens)
        self._compact_at = 4096

    # ------------------------------------------------------------------ logging
    def _log(self, kind: str, text: str) -> None:
        if self.log_callback:
            self.log_callback(kind, text)

    def _confirm(self, question: str, default: str = "Y") -> str:
        if self.confirm_callback:
            return self.confirm_callback(question, default)
        return default

    # ------------------------------------------------------------------ run
    def run(self, user_prompt: str) -> str:
        self._log("user", user_prompt)
        restart_count = 0
        original_prompt = user_prompt
        self._task_prompt = user_prompt
        while True:
            try:
                self._run_cycle(original_prompt, user_prompt)
                break
            except LoopDetected:
                restart_count += 1
                self._log("system", f"[loop detected] attempt #{restart_count}")
                # Two-phase fallback FIRST: tiny models loop in tool mode; text output + harness save works
                if self.spec.finish_hint and restart_count <= 2:
                    saved = self._two_phase_deliverable(original_prompt)
                    if saved:
                        return f"Task finished (two-phase): {saved} saved."
                if restart_count > 3:
                    # final: force a plain-text answer so the session still returns something useful
                    forced = self._force_text_answer(original_prompt)
                    return forced or "Task aborted: loop restarted 3+ times. Consider splitting the task."
                self.summary = self._summarize()
                self.ctx.reset_dedup()
                self.state.reset_loops()
                self._failed_reads = {}
                user_prompt = (
                    f"ORIGINAL TASK: {original_prompt}\n\n"
                    f"[Summary of previous attempt]: {self.summary}\n"
                    "Do not repeat already-successful tool calls. Do NOT add helper functions unless the original task asks for them. "
                    "Proceed directly to the next useful step, then answer."
                )
        if self.judge:
            self._run_judge()
        return self.last_result or "Task finished."

    # ------------------------------------------------------------------ core cycle
    def _run_cycle(self, original_prompt: str, user_prompt: str) -> None:
        self.state.turn_count = 0
        turn = 0
        answered = False
        while turn < self.max_turns and not answered:
            turn += 1
            self.state.turn_count = turn
            self._log("system", f"[turn {turn}/{self.max_turns}]")
            messages = self.ctx.build(
                system_prompt=render(self.spec, user_task=user_prompt, rules=Judge.load_rules(self.cwd), summary=self.summary, todo=self.todo, docs=self.rag.shell_ref(original_prompt)),
                user_prompt=user_prompt,
                history=self.history,
                todo=self.todo,
                summary=self.summary,
                extra=[("docs", self.rag.shell_ref(original_prompt))],
            )
            self._log("context", f"context={estimate_tokens(json.dumps(messages))} tokens, {len(messages)} messages")

            # aggressive compaction for tiny models: degrade starts ~4-5K tokens.
            # summarize history BEFORE the model call so the session stays fresh.
            if estimate_tokens(json.dumps(messages)) > self._compact_at and len(self.history) > 8:
                self._log("system", f"[context-watchdog] compacting at {self._compact_at} tokens")
                self.summary = self._summarize()
                self.ctx.reset_dedup()
                self.history = []
                messages = self.ctx.build(
                    system_prompt=render(self.spec, user_task=user_prompt, rules=Judge.load_rules(self.cwd), summary=self.summary, todo=self.todo, docs=self.rag.shell_ref(original_prompt)),
                    user_prompt=user_prompt,
                    history=self.history,
                    todo=self.todo,
                    summary=self.summary,
                    extra=[("docs", self.rag.shell_ref(original_prompt))],
                )
                self._log("context", f"context after compaction={estimate_tokens(json.dumps(messages))} tokens")

            response = self.client.chat(messages, tools=self.registry.schema(self.allowed_tools))
            self._log("model", f"text={response.text[:100]!r} tools={[c.name for c in response.tool_calls]}")

            # text repetition detection: same opening phrase repeated → nudge once, then restart
            if response.text.strip():
                key = response.text.strip()[:60]
                if key == self._last_text:
                    self._text_repeats += 1
                    if self._text_repeats >= 3:
                        self._log("system", "[text-repetition] model stuck — forcing final state answer")
                        self.last_result = (
                            "The model kept repeating the same sentence instead of working. "
                            f"Last tool results: {self._last_tool_summary()}"
                        )
                        answered = True
                        break
                    if self._text_repeats >= 2:
                        self._log("system", "[text-repetition] model repeating same phrase")
                        self._text_repeats = 0
                        self.history.append({
                            "role": "user",
                            "content": (
                                "[text-repetition] You are repeating the same sentence. STOP. "
                                "Look at the tool results already in this conversation and act on them: "
                                "either call the NEXT correct tool or answer in text."
                            ),
                        })
                        continue
                else:
                    self._last_text = key
                    self._text_repeats = 0

            if response.text:
                self.history.append({"role": "assistant", "content": response.text})

            if not response.has_tools:
                # code-in-chat detection → offer write
                if self._looks_like_code(response.text):
                    if self._confirm_code_write(response):
                        self.history.append({"role": "user", "content": "Write the code you just showed to a file using write_file. Do not paste code in chat."})
                        continue
                # L1: text-encoded tool calls
                corrected = self.recovery.recover(response)
                parsed = [c for c in corrected if c.call and c.call.name]
                if parsed:
                    self._log("system", f"[text-parser] recovered {len(parsed)} calls from text")
                    for c in parsed:
                        self._execute_corrected(c)
                    continue
                if not response.text.strip():
                    self.history.append({"role": "user", "content": "Your response was empty. State your next action or call a tool."})
                    continue
                # plain text answer → done (task considered answered)
                self.last_result = response.text.strip()
                if self.spec.finish_hint:
                    saved = self._capture_deliverable_text(response.text, self._task_prompt)
                    if saved:
                        self.last_result = f"{self.last_result}\n[auto-saved deliverable → {saved}]"
                answered = True
                continue

            # native tool calls → recovery pipeline
            corrected = self.recovery.recover(response)
            acted = False
            for c in corrected:
                if c.call:
                    self._execute_corrected(c)
                    acted = True
                else:
                    self.history.append({"role": "user", "content": f"[tool-recovery] {c.note}. Re-issue a valid tool call."})
            # nudge: guide toward completion without killing legitimate multi-step work
            if acted:
                last_tool = self.history[-3]["content"] if len(self.history) >= 3 else ""
                if "Tool: write_file" in last_tool or "Tool: edit_file" in last_tool:
                    self.history.append({"role": "user", "content": FINAL_NUDGE})
                else:
                    self.history.append({"role": "user", "content": ANSWER_NUDGE})

            # hard stop: edit applied + 2 blocked repeats → task is done, force final answer
            if self._edit_done and self._blocked_after_edit >= 2:
                self._log("system", "[force-complete] edit applied and model is stuck re-reading")
                self.last_result = (
                    "The requested change was applied to the file. The model kept trying to re-read it; "
                    "task considered complete."
                )
                answered = True

            # role finish_hint: stuck re-reading while a deliverable file is expected
            if self.spec.finish_hint and self._stuck_reads >= 2:
                self._log("system", "[force-complete] role deliverable expected, model stuck reading")
                done = self._two_phase_deliverable(original_prompt)
                if done:
                    answered = True
                elif not self._deliverable_tried:
                    self._deliverable_tried = True
                    self._stuck_reads = 0
                    self.history.append({
                        "role": "user",
                        "content": (
                            "STOP calling tools. Output the deliverable content as plain text "
                            "in your response (the full file content, nothing else). "
                            "I will save it to the file myself."
                        ),
                    })
                else:
                    answered = True

    # ------------------------------------------------------------------ execution
    def _execute_corrected(self, c: CorrectedCall) -> None:
        call = c.call
        if not call:
            return
        if call.name not in self.allowed_tools:
            self._log("system", f"[tool-gating] {call.name} not allowed for agent {self.agent_name}")
            self.history.append({"role": "user", "content": f"[tool-gating] Tool '{call.name}' is not in your allowed set: {self.allowed_tools}. Use an allowed tool."})
            return

        # loop detection on identical calls (window-based)
        # but when edit was applied, repeated reads are handled by guards + force-complete
        if self.state.record_tool_call(call.name, call.args):
            if not (self._edit_done and call.name in ("read_file", "bash")):
                self._log("system", f"[loop-detector] {call.name} repeated 3x in window")
                if self._corrections_injected < 1:
                    # cheap fix first: hard correction with real file list, then continue
                    self._corrections_injected += 1
                    files = self._file_list()
                    self.history.append({
                        "role": "user",
                        "content": (
                            "[hard-correction] You have repeated the same action 3 times. STOP repeating it.\n"
                            f"Actual files in the project root:\n{files}\n"
                            "Use read_file with EXACT paths from this list (relative, no prefixes). "
                            "If you already have the info you need, stop calling tools and answer in text."
                        ),
                    })
                else:
                    raise LoopDetected()

        arg_hash = json.dumps(call.args, sort_keys=True)

        # repeat full-read guard: same file fully read twice → content already in context
        if call.name == "read_file" and not call.args.get("offset") and not call.args.get("limit"):
            import os as _os

            path_key = str(call.args.get("path", ""))
            if path_key in self._failed_reads and self._failed_reads[path_key] >= 2:
                self._log("system", f"[path-blacklist] repeat attempt of {path_key}")
                self.history.append({
                    "role": "user",
                    "content": f"[path-blacklist] '{path_key}' was already proven non-existent. Stop trying it. Real files:\n{self._file_list()}",
                })
                return
            norm = _os.path.normpath(_os.path.join(self.cwd, call.args.get("path", "")))
            if norm in self.state.read_files:
                self._log("system", f"[read-repeat-guard] {call.args.get('path')} already fully read")
                self._stuck_reads += 1
                if self._edit_done:
                    self._blocked_after_edit += 1
                if self.spec.finish_hint:
                    self.history.append({
                        "role": "user",
                        "content": (
                            f"[read-repeat-guard] You already fully read '{call.args.get('path')}'. "
                            f"{self.spec.finish_hint}"
                        ),
                    })
                else:
                    self.history.append({
                        "role": "user",
                        "content": (
                            f"[read-repeat-guard] You already fully read '{call.args.get('path')}' — its content is in context. "
                            "Do NOT re-read the whole file. Proceed: edit_file to modify, or answer in text."
                        ),
                    })
                return

        # non-idempotent guard: same write/edit already done this session → refuse
        if call.name in ("write_file", "edit_file") and self.state.is_write_done(call.name, call.args):
            self._log("system", f"[idempotency-guard] {call.name} already applied")
            if self._edit_done:
                self._blocked_after_edit += 1
            self.history.append({
                "role": "user",
                "content": (
                    f"[idempotency-guard] You ALREADY executed {call.name}({json.dumps(call.args, ensure_ascii=False)[:200]}) successfully "
                    "in this session. Repeating it is forbidden (it would corrupt the file). "
                    "Read the current file state and answer the user in text."
                ),
            })
            return

        result: ToolResult = self.registry.execute(call.name, call.args)
        self._log("tool", f"{call.name}({json.dumps(call.args, ensure_ascii=False)[:200]}) -> ok={result.ok} err={result.error}")

        if not result.ok and result.error == "guarded":
            self._consecutive_corrections += 1
            # track repeated failed reads of the same path
            if call.name == "read_file":
                path = str(call.args.get("path", ""))
                self._failed_reads[path] = self._failed_reads.get(path, 0) + 1
                if self._failed_reads[path] >= 2:
                    self._log("system", f"[path-blacklist] {path} blocked (2 failed reads)")
                    self.history.append({
                        "role": "user",
                        "content": (
                            f"[path-blacklist] '{path}' does NOT exist. It has been blocked. "
                            f"Do NOT try to read it again. Real files in the project:\n{self._file_list()}\n"
                            "Use read_file with a real path from this list, or answer in text."
                        ),
                    })
                    return
            self.history.append({"role": "user", "content": f"[guard] {result.output}\n{result.meta.get('suggestion') or ''}"})
            # deterministic correction suggestion
            suggestion = correct_call(self.registry, call.name, call.args, result.output)
            if suggestion.ok and suggestion.suggestion:
                self.history.append({
                    "role": "user",
                    "content": f"[correction] {suggestion.note} Execute this instead? Reply with the corrected tool call, or answer in text.",
                })
            else:
                # guarded failures (wrong paths, permissions) → sub-agent with RAG + real file list
                self._subagent_recover(call, result.output)
            return

        if not result.ok:
            # bash exit_nonzero / tool runtime errors are USEFUL output → feed to the model,
            # don't treat as a broken call. Only invalid/guarded calls get correction.
            if call.name in ("bash",) and result.error in ("exit_nonzero",):
                self._consecutive_corrections = 0
                self._append_result(call.name, call.args, result)
                return
            self._consecutive_corrections += 1
            # error recovery: try deterministic fix, then sub-agent with RAG
            suggestion = correct_call(self.registry, call.name, call.args, result.output)
            if suggestion.ok and suggestion.suggestion:
                self._log("system", f"[deterministic-fix] {suggestion.note}")
                self.history.append({
                    "role": "user",
                    "content": f"[tool-error] {result.output}\n[deterministic-fix] {suggestion.note} Call: {suggestion.suggestion}",
                })
                # try the deterministic fix directly (bounded)
                fixed = suggestion.suggestion
                if self.state.record_tool_call(fixed["tool"], json.dumps(fixed["args"], sort_keys=True)):
                    raise LoopDetected()
                result2: ToolResult = self.registry.execute(fixed["tool"], fixed["args"])
                self._log("tool", f"fix-> {fixed['tool']}({fixed['args']}) ok={result2.ok}")
                if result2.ok:
                    if fixed["tool"] in ("write_file", "edit_file"):
                        self.state.mark_write_done(fixed["tool"], fixed["args"])
                    self._append_result(fixed["tool"], fixed["args"], result2)
                    return
                self.history.append({"role": "user", "content": f"[tool-error] deterministic fix also failed: {result2.output[:300]}"})
            else:
                # sub-agent corrector with RAG docs
                self._subagent_recover(call, result.output)
            return

        # success
        self._consecutive_corrections = 0
        if call.name in ("write_file", "edit_file"):
            self.state.mark_write_done(call.name, call.args)
            self._edit_done = True
            self._blocked_after_edit = 0
        self._append_result(call.name, call.args, result)

    def _append_result(self, name: str, args: dict, result: ToolResult) -> None:
        body = result.output
        if estimate_tokens(body) > 900:
            body = body[:2700] + "\n...[truncated]"
        self.history.append({"role": "assistant", "content": f"Tool: {name}({json.dumps(args, ensure_ascii=False)})"})
        self.history.append({"role": "user", "content": f"Tool result:\n{body}"})
        self.last_result = body

    def _subagent_recover(self, call, error: str) -> None:
        """Sub-agent picks the right tool by intent + RAG docs; main model confirms."""
        if self._consecutive_corrections > 3:
            self.history.append({"role": "user", "content": "[tool-error] Too many consecutive failures. Stop and answer in text."})
            return
        self._log("system", f"[sub-agent] correcting failed call {call.name}")
        intent = f"Main agent tried: {call.name}({call.args}) and got: {error[:300]}\n\nActual files in the project:\n{self._file_list()}"
        try:
            proposal, reasoning = self.corrector.propose(intent, error, {"tool": call.name, "args": call.args})
        except Exception as e:  # noqa: BLE001
            self.history.append({"role": "user", "content": f"[sub-agent] failed: {e}. Answer in text instead."})
            return
        if not proposal:
            self.history.append({"role": "user", "content": f"[sub-agent] {reasoning} Answer in text instead."})
            return
        # sub-agent repetition guard: identical proposal twice → stop suggesting
        key = json.dumps(proposal, sort_keys=True)
        if key == self._last_subagent_proposal:
            self._subagent_repeats += 1
        else:
            self._subagent_repeats = 0
        self._last_subagent_proposal = key
        if self._subagent_repeats >= 2:
            self._log("system", "[sub-agent-guard] same proposal repeated — disabled for this call")
            self.history.append({
                "role": "user",
                "content": (
                    "[sub-agent-guard] The corrector proposed the same (invalid) call twice. "
                    "Propose something DIFFERENT: re-read the error, use the real file list, "
                    "or answer in text."
                ),
            })
            return
        question = (
            f"[sub-agent] proposes: {proposal['tool']}({json.dumps(proposal['args'], ensure_ascii=False)})\n"
            f"Reasoning: {reasoning}\n"
            "Approve? (Y/n) — n to request changes."
        )
        answer = self._confirm(question, "Y")
        if answer.strip().lower().startswith("n"):
            self.history.append({"role": "user", "content": "[sub-agent] proposal rejected by user. Fix the call yourself or answer in text."})
            return
        # validate before execution
        ok, verr = self.registry.validate(proposal["tool"], proposal["args"])
        if not ok:
            self.history.append({"role": "user", "content": f"[sub-agent] proposal invalid: {verr}. Fix or answer in text."})
            return
        if proposal["tool"] not in self.allowed_tools:
            self.history.append({"role": "user", "content": f"[sub-agent] tool '{proposal['tool']}' not allowed for this agent."})
            return
        result = self.registry.execute(proposal["tool"], proposal["args"])
        if result.ok:
            if proposal["tool"] in ("write_file", "edit_file"):
                self.state.mark_write_done(proposal["tool"], proposal["args"])
            self._append_result(proposal["tool"], proposal["args"], result)
        else:
            self.history.append({"role": "user", "content": f"[sub-agent] execution failed: {result.output[:300]}. Fix or answer in text."})

    # ------------------------------------------------------------------ helpers
    def _last_tool_summary(self) -> str:
        """Summarize the last successful tool results for the final answer."""
        recent = [m["content"] for m in self.history[-8:] if m["role"] == "user" and m["content"].startswith("Tool result")]
        if not recent:
            return "(no tool results recorded)"
        body = "\n".join(r[:400] for r in recent[-3:])
        return body or "(empty)"

    def _force_text_answer(self, original_prompt: str) -> str | None:
        """Ask the model one final question in pure text mode (no tools) and return its answer."""
        self._log("system", "[force-text] requesting final answer without tools")
        try:
            history = [m for m in self.history[-10:] if m["role"] in ("user", "assistant") and not m["content"].startswith(("[", "Tool:"))]
            resp = self.client.chat(
                [
                    {"role": "system", "content": render(self.spec, user_task=original_prompt)},
                    *history,
                    {"role": "user", "content": "Answer in plain text (no tools): what did you find out / do? Be concise."},
                ],
                tools=None,
            )
            if resp.text.strip():
                return resp.text.strip()
        except Exception as e:  # noqa: BLE001
            self._log("system", f"[force-text] failed: {e}")
        return None

    def _two_phase_deliverable(self, original_prompt: str) -> bool:
        """Phase 2 of artifact generation: request plain-text content, then save it."""
        self._log("system", "[two-phase] requesting deliverable as plain text")
        try:
            history = [m for m in self.history[-12:] if m["role"] in ("user", "assistant") and not m["content"].startswith(("[", "Tool:"))]
            messages: list[dict[str, Any]] = [
                {"role": "system", "content": render(self.spec, user_task=original_prompt)},
                *history,
                {
                    "role": "user",
                    "content": (
                        "Output the deliverable file content as plain text in your response. "
                        "Do NOT call tools. Do NOT add explanations. Just the file content "
                        f"(code for the task: {original_prompt})."
                    ),
                },
            ]
            resp = self.client.chat(messages, tools=None)
            if resp.text.strip():
                saved = self._capture_deliverable_text(resp.text, original_prompt)
                if saved:
                    self.last_result = f"[deliverable saved → {saved}]"
                    return True
                self._log("system", f"[two-phase] no capturable content: {resp.text[:120]!r}")
        except Exception as e:  # noqa: BLE001
            self._log("system", f"[two-phase] failed: {e}")
        return False

    def _capture_deliverable_text(self, text: str, task_prompt: str | None = None) -> str | None:
        """Detect ARCHITECTURE.md / TASKS.md / code content in model text and save it."""
        import re as _re

        if not self.spec.finish_hint:
            return None
        target = "TASKS.md" if "TASKS.md" in self.spec.finish_hint else "ARCHITECTURE.md"
        # code deliverable (implementer): extract fenced python block
        if "write_file" in self.spec.finish_hint and ".py" in self.spec.finish_hint:
            m = _re.search(r"```(?:python|py)?\s*(.*?)```", text, flags=_re.S)
            if not m:
                return None
            content = m.group(1).strip()
            pyfile = _re.search(r"([A-Za-z_][A-Za-z0-9_]*\.py)", (task_prompt or "") + " " + text)
            target = pyfile.group(1) if pyfile else "module.py"
            if len(content) < 20:
                return None
            path = os.path.join(self.cwd, target)
            if os.path.exists(path):
                return None
            with open(path, "w", encoding="utf-8") as f:
                f.write(content + "\n")
            self._log("system", f"[deliverable] saved {target} ({len(content)} chars)")
            return target
        # markdown deliverable (architect / planner)
        m = _re.search(r"```(?:markdown|md)?\s*(.*?)```", text, flags=_re.S)
        content = m.group(1) if m else text
        # drop leading chatter before '# ' or first task marker
        lines = content.splitlines()
        start = 0
        for i, line in enumerate(lines):
            if line.strip().startswith("# ") or _re.match(r"^\s*[-#]+\s*T?\d+\.", line.strip()):
                start = i
                break
        content = "\n".join(lines[start:]).strip()
        if len(content) < 50:
            return None
        content = _dedupe_doc_tasks(content)
        path = os.path.join(self.cwd, target)
        if os.path.exists(path):
            return None
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content + "\n")
            self._log("system", f"[deliverable] saved {target} ({len(content)} chars)")
            return target
        except OSError as e:
            self._log("system", f"[deliverable] write failed: {e}")
            return None

    def _file_list(self, limit: int = 15) -> str:
        import os as _os

        try:
            names = sorted(_os.listdir(self.cwd))
        except OSError:
            return "(cannot list directory)"
        shown = []
        for n in names:
            if n.startswith("."):
                continue  # hidden artifacts are not valid file targets
            full = _os.path.join(self.cwd, n)
            shown.append(f"{n}/" if _os.path.isdir(full) else n)
            if len(shown) >= limit:
                break
        return "\n".join(shown) if shown else "(project root is empty)"

    def _summarize(self) -> str:
        try:
            prompt = self.ctx.build_summary_prompt(self.history)
            resp = self.client.chat([{"role": "user", "content": prompt}], tools=None)
            summary = resp.text.strip()
            if summary and not resp.has_tools:
                self._log("system", f"[summary] {summary[:200]}")
                return summary[: MAX_SUMMARY_TOKENS * 3]
        except Exception as e:  # noqa: BLE001
            self._log("system", f"[summary] failed: {e}")
        for m in reversed(self.history):
            if m["role"] == "user" and not m["content"].startswith("[") and "Tool result" not in m["content"]:
                return m["content"][:400]
        return ""

    def _looks_like_code(self, text: str) -> bool:
        lines = [l for l in text.splitlines() if l.strip()]
        if len(lines) < 5:
            return False
        codeish = 0
        for l in lines:
            l = l.strip()
            if l.startswith(("def ", "class ", "import ", "from ", "function ", "const ", "let ", "var ", "#", "//", "/*", "```", "return ", "async ")):
                codeish += 1
            elif l.startswith(("    ", "\t")) and len(l) > 4:
                codeish += 1
        return codeish >= max(3, len(lines) // 3)

    def _confirm_code_write(self, response: ModelResponse) -> bool:
        self.state.code_offers += 1
        if self.state.code_offers > 3:
            return True
        answer = self._confirm(
            f"The model wrote code in chat ({len(response.text.splitlines())} lines) instead of a file. Write to file? (Y/n): ",
            "Y",
        )
        return answer.strip().lower() != "n"

    # ------------------------------------------------------------------ judge
    def _run_judge(self) -> None:
        verdict = self.judge.evaluate(self.history)
        if not verdict:
            return
        if "error" in verdict:
            self._log("judge", f"failed: {verdict['error']}")
            return
        score = verdict.get("score", 0)
        issues = verdict.get("issues", [])
        self._log("judge", f"score={score} issues={issues[:2]}")
