from __future__ import annotations

from typing import Any

from tools.base import Tool, ToolError, ToolResult


class Registry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools.keys())

    def schema(self, allowed: list[str] | None = None) -> list[dict[str, Any]]:
        if allowed is None:
            return [t.schema() for t in self._tools.values()]
        return [self._tools[n].schema() for n in allowed if n in self._tools]

    def validate(self, name: str, args: dict[str, Any]) -> tuple[bool, str | None]:
        tool = self._tools.get(name)
        if tool is None:
            return False, f"Unknown tool: {name}"
        required = tool.parameters.get("required", [])
        props = tool.parameters.get("properties", {})
        for r in required:
            if r not in args or args[r] is None:
                return False, f"Missing required argument '{r}' for {name}. Expected: {', '.join(props)}"
        for k, v in args.items():
            if k not in props:
                return False, f"Unknown argument '{k}' for {name}. Allowed: {', '.join(props)}"
            schema_type = props[k].get("type", "string")
            if schema_type == "string" and not isinstance(v, str):
                return False, f"Argument '{k}' must be a string, got {type(v).__name__} ({v!r})."
            if schema_type == "integer" and not isinstance(v, int):
                return False, f"Argument '{k}' must be an integer, got {type(v).__name__} ({v!r})."
            if schema_type == "boolean" and not isinstance(v, bool):
                return False, f"Argument '{k}' must be a boolean, got {type(v).__name__} ({v!r})."
        return True, None

    def execute(self, name: str, args: dict[str, Any]) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult.failure(f"Unknown tool: {name}", error="unknown_tool")
        try:
            ok, err = self.validate(name, args)
            if not ok:
                return ToolResult.failure(f"Validation error: {err}", error="invalid_args", meta={"tool": name, "args": args})
            try:
                tool.guard(**args)
            except ToolError as e:
                return ToolResult.failure(e.message, error="guarded", meta={"tool": name, "suggestion": e.suggestion, "args": args})
            return tool.execute(**args)
        except ToolError as e:
            return ToolResult.failure(e.message, error="tool_error", meta={"tool": name, "suggestion": e.suggestion, "args": args})
        except Exception as e:  # noqa: BLE001
            return ToolResult.failure(f"Tool '{name}' crashed: {e!r}", error="tool_error", meta={"tool": name, "args": args})


_global: Registry | None = None


def get_registry() -> Registry:
    global _global
    if _global is None:
        _global = Registry()
    return _global
