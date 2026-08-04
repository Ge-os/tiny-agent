from __future__ import annotations

"""Sub-agent corrector: repairs tool calls using RAG docs + tool schemas.

Flow (README §5.2):
  1. Main agent's tool call failed (or intent extracted from text).
  2. Sub-agent gets: intent + error + tool schemas + RAG shell/docs reference.
  3. Sub-agent picks the closest tool+args by meaning, returns JSON.
  4. Main model (or user) approves / rejects with a fix comment.
"""

import json
from typing import Any

from app.api import ApiClient
from app.prompts.roles import get_agent, render
from app.rag import Rag
from tools.registry import Registry

MAX_SUBAGENT_RETRIES = 2


class SubagentError(Exception):
    pass


class ToolCorrector:
    def __init__(self, client: ApiClient, registry: Registry, rag: Rag):
        self.client = client
        self.registry = registry
        self.rag = rag
        self.spec = get_agent("subagent_corrector")

    def propose(self, intent: str, error: str | None, failed_call: dict | None = None) -> tuple[dict | None, str]:
        """Returns (tool_call_dict, reasoning). tool_call_dict=None on failure."""
        tool_schemas = json.dumps(self.registry.schema(), ensure_ascii=False, indent=1)[:4000]
        docs = self.rag.shell_ref(intent)
        attempt = 0
        comment = ""
        while attempt < MAX_SUBAGENT_RETRIES:
            attempt += 1
            sys_prompt = render(
                self.spec,
                user_task=intent,
                error=(error or "") + ("\nComment from main agent: " + comment if comment else ""),
                tool_schemas=tool_schemas,
                docs=docs or "(no docs available)",
            )
            try:
                resp = self.client.chat(
                    [{"role": "system", "content": sys_prompt}, {"role": "user", "content": intent}],
                    tools=None,
                )
            except Exception as e:  # noqa: BLE001
                raise SubagentError(f"sub-agent call failed: {e}") from e
            call, reasoning = self._parse(resp.text)
            if call:
                ok, verr = self.registry.validate(call["tool"], call["args"])
                if ok:
                    return call, reasoning
                # heuristic: model named a shell command as tool → wrap into bash
                wrapped = self._wrap_as_bash(call)
                if wrapped:
                    return wrapped, reasoning + " (wrapped command as bash tool)"
                error = f"Validation error: {verr}"
                comment = ""
                continue
            if attempt >= MAX_SUBAGENT_RETRIES:
                break
        return None, f"Sub-agent could not produce a valid tool call after {MAX_SUBAGENT_RETRIES} attempts."

    @staticmethod
    def _wrap_as_bash(call: dict) -> dict | None:
        """If the model named a shell command as a tool (e.g. 'python -m pytest'),
        wrap it into a bash call: bash(command='<tool> <args>')."""
        tool = call.get("tool") or ""
        if tool in ("bash", "Bash", "shell"):
            return call
        first = tool.split()[0].lower()
        KNOWN_BINARIES = ("python", "python3", "py", "node", "npm", "pip", "pip3", "git", "ls", "cat", "head", "tail", "grep", "find", "pwd", "echo", "wc", "mkdir", "touch", "cp", "mv", "pytest", "go", "cargo", "dotnet", "type", "dir")
        if first in KNOWN_BINARIES or (len(tool.split()) > 1 and first not in ("read_file", "write_file", "edit_file")):
            args = dict(call.get("args") or {})
            extra = ""
            path = args.pop("path", None)
            if path:
                extra = f" {path}"
            cmd = tool + extra
            return {"tool": "bash", "args": {"command": cmd}}
        return None

    @staticmethod
    def _parse(text: str) -> tuple[dict | None, str]:
        text = text.strip()
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end < 0:
            return None, ""
        try:
            obj = json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            return None, ""
        tool = obj.get("tool")
        args = obj.get("args") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}
        if not isinstance(tool, str) or not isinstance(args, dict):
            return None, ""
        return {"tool": tool, "args": args}, str(obj.get("reasoning", ""))


def extract_intent_from_response(text: str) -> str | None:
    """When the model answers in natural language instead of a tool call,
    extract the intent from the last line mentioning an action."""
    if not text or len(text) < 3:
        return None
    lines = [l for l in text.strip().splitlines() if l.strip()]
    if not lines:
        return None
    return lines[-1][:300]
