from __future__ import annotations

import dataclasses
from typing import Any, Callable


@dataclasses.dataclass
class ToolResult:
    ok: bool
    output: str
    error: str | None = None
    meta: dict[str, Any] = dataclasses.field(default_factory=dict)

    @classmethod
    def success(cls, output: str, **meta: Any) -> "ToolResult":
        return cls(ok=True, output=output, meta=meta)

    @classmethod
    def failure(cls, output: str, error: str | None = None, **meta: Any) -> "ToolResult":
        return cls(ok=False, output=output, error=error, meta=meta)


class ToolError(Exception):
    """Raised by guards to block execution before it starts."""

    def __init__(self, message: str, suggestion: str | None = None, meta: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.suggestion = suggestion
        self.meta = meta or {}


class Tool:
    """Base class for all tools.

    Subclasses define `name`, `description`, `parameters` (JSON Schema)
    and implement `execute(**kwargs) -> ToolResult`.
    Optional `guard(**kwargs)` raises ToolError to block execution.
    """

    name: str = ""
    description: str = ""
    parameters: dict[str, Any] = {"type": "object", "properties": {}, "required": []}

    def guard(self, **kwargs: Any) -> None:
        """Pre-execution check. Raise ToolError to block."""

    def execute(self, **kwargs: Any) -> ToolResult:
        raise NotImplementedError

    def schema(self) -> dict[str, Any]:
        return {"type": "function", "function": {"name": self.name, "description": self.description, "parameters": self.parameters}}

    # --- shared helpers ---------------------------------------------------

    @staticmethod
    def read_ok(path: str) -> str:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                return f.read()
        except UnicodeDecodeError:
            raise ToolError(f"File '{path}' is binary or not text-readable. Use grep/strings instead.")
        except FileNotFoundError:
            raise ToolError(f"File '{path}' does not exist.")
        except IsADirectoryError:
            raise ToolError(f"'{path}' is a directory, not a file. Use ls instead.")
        except OSError as e:
            raise ToolError(f"Cannot read '{path}': {e}")

    @staticmethod
    def ensure_safe_path(path: str) -> str:
        if "\x00" in path:
            raise ToolError("NUL byte in path.")
        if any(ch in path for ch in [".."] ):
            pass  # allow relative .. — project tools run inside cwd
        return path
