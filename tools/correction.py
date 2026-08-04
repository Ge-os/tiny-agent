from __future__ import annotations

"""Deterministic tool-call correction (level 1-2 of the recovery pipeline).

Given a failed tool call + error, produce a corrected suggestion WITHOUT any LLM call:
  - unknown tool name → similarity match (difflib)
  - wrong types / missing required → fix types / fill from error message
"""

import re
from typing import Any

from app.api import similarity_match
from tools.registry import Registry


class DeterministicSuggestion:
    def __init__(self, ok: bool, suggestion: dict | None = None, note: str = ""):
        self.ok = ok
        self.suggestion = suggestion
        self.note = note


def _coerce_arg(value: Any, schema_type: str) -> Any:
    if schema_type == "string" and not isinstance(value, str):
        return str(value)
    if schema_type == "integer" and isinstance(value, str):
        m = re.search(r"\d+", value)
        return int(m.group(0)) if m else None
    if schema_type == "boolean" and isinstance(value, str):
        return value.lower() in ("true", "1", "yes")
    return value


def correct_call(registry: Registry, tool_name: str, args: dict[str, Any], error: str | None = None) -> DeterministicSuggestion:
    """Try to deterministically repair a failed tool call."""
    # 1. unknown tool name → closest known
    tool = registry.get(tool_name)
    if tool is None:
        match = similarity_match(tool_name, registry.names())
        if match:
            return DeterministicSuggestion(
                ok=True,
                suggestion={"tool": match, "args": args},
                note=f"Unknown tool '{tool_name}' → suggested '{match}' (name similarity).",
            )
        return DeterministicSuggestion(ok=False, note=f"Unknown tool '{tool_name}'. Available: {registry.names()}")

    # 2. coerce argument types per schema
    props = tool.parameters.get("properties", {})
    new_args = dict(args)
    changed = False
    for key, val in list(new_args.items()):
        if key not in props:
            continue
        schema_type = props[key].get("type", "string")
        fixed = _coerce_arg(val, schema_type)
        if fixed is not None and fixed != val:
            new_args[key] = fixed
            changed = True

    # 3. fill missing required from bare-value args ({"path": "x"} style already handled)
    required = tool.parameters.get("required", [])
    missing = [r for r in required if r not in new_args]
    if missing and not changed:
        return DeterministicSuggestion(
            ok=False,
            note=f"Missing required arguments {missing} for '{tool_name}'. Provide: {list(props)}",
        )
    if changed:
        return DeterministicSuggestion(
            ok=True,
            suggestion={"tool": tool_name, "args": new_args},
            note=f"Fixed argument types for '{tool_name}': {new_args}",
        )
    return DeterministicSuggestion(ok=False, note=error or "Validation failed.")
