from __future__ import annotations

"""LLM-as-judge: post-task retrospective → score + rules.

Reads the conversation log, asks the judge model (preferably a stronger/cloud model),
parses the JSON verdict, saves rules into <project>/.tiny-agent/rules/.
"""

import json
import os
import re
import time
from typing import Any

from app.api import ApiClient
from app.prompts.roles import get_agent, render

MAX_RULES = 2
RULE_TTL_SESSIONS = 5
MAX_LOG_CHARS = 12000


class Judge:
    def __init__(self, client: ApiClient, cwd: str, model_name: str = "judge"):
        self.client = client
        self.cwd = cwd
        self.spec = get_agent("judge")
        self.model_name = model_name

    # ------------------------------------------------------------------ run
    def evaluate(self, history: list[dict[str, Any]]) -> dict[str, Any] | None:
        try:
            log = json.dumps(history[-40:], ensure_ascii=False, default=str)[:MAX_LOG_CHARS]
            sys_prompt = render(self.spec)
            resp = self.client.chat(
                [
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": "Evaluate the following agent conversation:\n" + log},
                ],
                tools=None,
            )
            verdict = self._parse(resp.text)
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)}
        if not verdict:
            return {"error": "judge returned unparseable output"}
        self._save_rules(verdict.get("rules", []))
        return verdict

    # ------------------------------------------------------------------ parse
    @staticmethod
    def _parse(text: str) -> dict[str, Any] | None:
        text = text.strip()
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end < 0:
            return None
        try:
            obj = json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            # try to extract score only
            m = re.search(r'"score"\s*:\s*(\d+)', text)
            return {"score": int(m.group(1)) if m else 0, "issues": [], "rules": []}
        if "score" not in obj:
            return None
        return {
            "score": int(obj.get("score", 0)),
            "issues": obj.get("issues") or [],
            "rules": obj.get("rules") or [],
        }

    # ------------------------------------------------------------------ rules
    def _save_rules(self, rules: list[str]) -> list[str]:
        if not rules:
            return []
        rules_dir = os.path.join(self.cwd, ".tiny-agent", "rules")
        os.makedirs(rules_dir, exist_ok=True)
        saved = []
        # prune: keep only last RULE_TTL_SESSIONS*2 rule files (crude TTL)
        existing = sorted(f for f in os.listdir(rules_dir) if f.endswith(".md"))
        if len(existing) > RULE_TTL_SESSIONS * 2:
            for f in existing[: len(existing) - RULE_TTL_SESSIONS * 2]:
                try:
                    os.remove(os.path.join(rules_dir, f))
                except OSError:
                    pass
        for i, rule in enumerate(rules[:MAX_RULES]):
            fname = f"judge_{int(time.time())}_{i}.md"
            with open(os.path.join(rules_dir, fname), "w", encoding="utf-8") as f:
                f.write(rule if rule.endswith("\n") else rule + "\n")
            saved.append(fname)
        return saved

    @staticmethod
    def load_rules(cwd: str, limit: int = 5) -> str:
        rules_dir = os.path.join(cwd, ".tiny-agent", "rules")
        parts = []
        if os.path.isdir(rules_dir):
            for f in sorted(os.listdir(rules_dir))[-limit:]:
                if f.endswith(".md"):
                    try:
                        parts.append(open(os.path.join(rules_dir, f), encoding="utf-8").read()[:500])
                    except OSError:
                        pass
        if not parts:
            return ""
        return "Rules (from LLM-as-judge, must be followed):\n" + "\n---\n".join(parts)
