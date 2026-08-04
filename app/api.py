from __future__ import annotations

"""OpenAI-compatible API client with anti-hallucination tool-call recovery.

Strategies (from README §5 Tool Calling Recovery):
  L1 — text parser: model emits tool calls as text (fenced JSON, <tool_call>, bare JSON)
  L2 — similarity match: hallucinated tool names → closest real name via difflib
"""

import json
import os
import re
import time
from typing import Any, Callable, Iterator

from openai import OpenAI

from tools.guards.state import estimate_tokens


class ToolCall:
    def __init__(self, name: str, args: dict[str, Any], raw: Any = None):
        self.name = name
        self.args = args
        self.raw = raw

    def __repr__(self) -> str:
        return f"ToolCall({self.name}({self.args}))"


class ModelResponse:
    def __init__(self, text: str = "", tool_calls: list[ToolCall] | None = None, raw: Any = None):
        self.text = text
        self.tool_calls = tool_calls or []
        self.raw = raw

    @property
    def has_tools(self) -> bool:
        return bool(self.tool_calls)

    def __repr__(self) -> str:
        return f"ModelResponse(text={self.text[:60]!r}, tools={len(self.tool_calls)})"


class TextToolParser:
    """Extract tool calls encoded as text in model output (L1 recovery)."""

    FENCED_RE = re.compile(r"```tool\s*([\s\S]*?)```", re.IGNORECASE)
    TAG_RE = re.compile(r"<tool_call>\s*([\s\S]*?)</tool_call>", re.IGNORECASE)
    PYTHONIC_RE = re.compile(r"<\|tool_call_start\|>([\s\S]*?)<\|tool_call_end\|>", re.IGNORECASE)

    @classmethod
    def repair_json(cls, s: str) -> str:
        s = s.strip()
        # unquoted keys
        s = re.sub(r"([{,\s])([A-Za-z_][A-Za-z0-9_]*)\s*:", r'\1"\2":', s)
        # single quotes → double (careful: escaped singles)
        s = re.sub(r"'", '"', s)
        # trailing commas
        s = re.sub(r",\s*([}\]])", r"\1", s)
        return s

    @classmethod
    def parse_json_call(cls, body: str) -> ToolCall | None:
        try:
            obj = json.loads(body)
        except json.JSONDecodeError:
            try:
                obj = json.loads(cls.repair_json(body))
            except json.JSONDecodeError:
                return None
        if isinstance(obj, dict):
            name = obj.get("name") or obj.get("tool")
            if isinstance(name, str):
                args = obj.get("input") or obj.get("arguments") or obj.get("args") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                if not isinstance(args, dict):
                    args = {}
                return ToolCall(name=name, args=args)
            # single-argument form like {"path": "x"}
            keys = [k for k in obj if k not in ("tool", "name", "input", "arguments", "args")]
            if keys and isinstance(obj[keys[0]], (str, int, bool, float)):
                return ToolCall(name="", args=obj, raw=obj)
        return None

    @classmethod
    def parse_pythonic(cls, body: str) -> ToolCall | None:
        """Parse Liquid/LFM2 style: [Read(path='/a.c')]"""
        m = re.match(r"\s*(\w+)\s*\(([^)]*)\)\s*", body.strip())
        if not m:
            return None
        name = m.group(1)
        raw_args = m.group(2)
        args: dict[str, Any] = {}
        for part in raw_args.split(","):
            part = part.strip()
            if not part or "=" not in part:
                continue
            k, _, v = part.partition("=")
            v = v.strip()
            if v.startswith("'") or v.startswith('"'):
                args[k.strip()] = v[1:-1]
            elif v in ("True", "False"):
                args[k.strip()] = v == "True"
            elif v.isdigit():
                args[k.strip()] = int(v)
            else:
                args[k.strip()] = v
        return ToolCall(name=name, args=args)

    @classmethod
    def extract(cls, text: str) -> list[ToolCall]:
        calls: list[ToolCall] = []
        for m in cls.FENCED_RE.finditer(text) + cls.TAG_RE.finditer(text) if False else cls._all_patterns(text):
            c = cls.parse_json_call(m.group(1))
            if c and (c.name or "input" not in c.args):
                calls.append(c)
        for m in cls.PYTHONIC_RE.finditer(text):
            c = cls.parse_pythonic(m.group(1))
            if c:
                calls.append(c)
        # bare JSON at the end (last standalone object)
        if not calls:
            body = text.strip().strip("`")
            if body.startswith("{") and body.endswith("}"):
                c = cls.parse_json_call(body)
                if c and c.name:
                    calls.append(c)
        return calls

    @classmethod
    def _all_patterns(cls, text: str) -> list[re.Match]:
        return list(cls.FENCED_RE.finditer(text)) + list(cls.TAG_RE.finditer(text))


def similarity_match(name: str, candidates: list[str], cutoff: float = 0.6) -> str | None:
    """L2: find closest known tool name for a hallucinated one."""
    import difflib

    name_l = name.lower()
    exact = [c for c in candidates if c.lower() == name_l]
    if exact:
        return exact[0]
    matches = difflib.get_close_matches(name_l, [c.lower() for c in candidates], n=3, cutoff=cutoff)
    if not matches:
        return None
    idx = [c.lower() for c in candidates].index(matches[0])
    return candidates[idx]


class ApiClient:
    def __init__(
        self,
        endpoint: str,
        model: str,
        api_key_env: str | None = None,
        context_window: int = 8192,
        max_tokens: int = 1024,
        temperature: float = 0.2,
        timeout: int = 120,
        enable_thinking: bool = False,
    ):
        self.model = model
        self.endpoint = endpoint
        self.max_tokens = max_tokens
        self.context_window = context_window
        self.temperature = temperature
        self.timeout = timeout
        self.enable_thinking = enable_thinking
        self.client = OpenAI(
            base_url=endpoint,
            api_key=os.environ.get(api_key_env) if api_key_env else "noop",
            timeout=timeout,
        )
        self.on_stream_chunk: Callable[[str], None] | None = None

    def health_check(self) -> bool:
        try:
            self.client.models.list()
            return True
        except Exception:
            return False

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_retries: int = 3,
    ) -> ModelResponse:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": True,
        }
        if not self.enable_thinking:
            kwargs["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        text_parts: list[str] = []
        tool_calls: dict[int, dict[str, Any]] = {}
        tool_order: list[int] = []
        retries = 0
        while True:
            try:
                stream = self.client.chat.completions.create(**kwargs)
                for chunk in stream:
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
                    if delta is None:
                        continue
                    if delta.content:
                        text_parts.append(delta.content)
                        if self.on_stream_chunk:
                            self.on_stream_chunk(delta.content)
                    if getattr(delta, "tool_calls", None):
                        for tc in delta.tool_calls:
                            idx = tc.index
                            if idx not in tool_calls:
                                tool_calls[idx] = {"name": "", "args": ""}
                                tool_order.append(idx)
                            if tc.function.name:
                                tool_calls[idx]["name"] += tc.function.name
                            if tc.function.arguments:
                                tool_calls[idx]["args"] += tc.function.arguments
                break
            except Exception as e:  # network / server errors → exponential backoff
                retries += 1
                if retries > max_retries:
                    raise RuntimeError(f"API failed after {max_retries} retries: {e}") from e
                time.sleep(2 ** retries)
        text = "".join(text_parts)
        calls = []
        for idx in tool_order:
            name = tool_calls[idx]["name"]
            try:
                args = json.loads(tool_calls[idx]["args"] or "{}")
            except json.JSONDecodeError:
                args = {}
            calls.append(ToolCall(name=name, args=args))
        return ModelResponse(text=text, tool_calls=calls)


class CorrectedCall:
    """Result of tool-call recovery: either a corrected call or a human-answer needed."""

    def __init__(self, call: ToolCall | None, note: str = "", options: list[str] | None = None):
        self.call = call
        self.note = note
        self.options = options or []

    def __repr__(self) -> str:
        return f"CorrectedCall(call={self.call}, note={self.note!r}, options={self.options})"


class ToolCallRecovery:
    """Pipeline: native calls → text-parser → similarity-match → (subagent fallback placeholder)."""

    def __init__(self, registry):
        self.registry = registry

    def recover(self, response: ModelResponse) -> list[CorrectedCall]:
        results: list[CorrectedCall] = []
        for call in response.tool_calls:
            results.append(self._recover_one(call))
        if response.has_tools:
            return results
        # L1: text parser
        for parsed in TextToolParser.extract(response.text):
            results.append(self._recover_one(parsed))
        return results

    def _recover_one(self, call: ToolCall) -> CorrectedCall:
        if self.registry.get(call.name):
            return CorrectedCall(call=call)
        # L2: similarity
        match = similarity_match(call.name, self.registry.names())
        if match:
            return CorrectedCall(
                call=ToolCall(name=match, args=call.args),
                note=f"Tool '{call.name}' does not exist — did you mean '{match}'?",
            )
        return CorrectedCall(call=None, note=f"Unknown tool '{call.name}'. Available: {', '.join(self.registry.names())}")
