from __future__ import annotations

import os
from pathlib import Path

from tools.base import Tool, ToolError, ToolResult
from tools.guards.state import SessionState, estimate_tokens
from tools.guards.write_guard import is_binary, normalize_write_path, safe_write

MAX_READ_LINES = 2000
TRUNCATE_FIRST_LINES = 30


class ReadFileTool(Tool):
    name = "read_file"
    description = (
        "Read the contents of a file with line numbers. "
        "If the file is large, it is truncated — then use grep to locate the section you need."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the file, relative to project root"},
            "offset": {"type": "integer", "description": "Line number to start from (1-based)"},
            "limit": {"type": "integer", "description": "Max lines to read"},
        },
        "required": ["path"],
    }

    def __init__(self, cwd: str, state: SessionState, context: dict | None = None):
        self.cwd = cwd
        self.state = state
        self.context = context or {}

    def _abs(self, path: str) -> str:
        return os.path.normpath(os.path.join(self.cwd, normalize_write_path(path, self.cwd)))

    def guard(self, path: str, **kwargs) -> None:
        p = self._abs(path)
        if not os.path.exists(p):
            hint = ""
            if os.path.isdir(os.path.dirname(p)):
                try:
                    names = [n for n in sorted(os.listdir(os.path.dirname(p)))[:10]]
                    hint = f" Directory contains: {', '.join(names)}"
                except OSError:
                    pass
            raise ToolError(f"File '{path}' does not exist.{hint}")
        if os.path.isdir(p):
            raise ToolError(f"'{path}' is a directory, not a file. Use ls.")
        if is_binary(p):
            raise ToolError(f"File '{path}' is binary. Use grep or bash to inspect it.")

    def execute(self, path: str, offset: int | None = None, limit: int | None = None) -> ToolResult:
        p = self._abs(path)
        self.state.mark_read(p)
        try:
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except OSError as e:
            return ToolResult.failure(f"Cannot read '{path}': {e}", error="os_error")
        total = len(lines)
        if offset:
            start = max(1, offset)
        else:
            start = 1
        end = min(total, start + (limit or MAX_READ_LINES) - 1)
        if limit and offset:
            end = min(total, start + limit - 1)
        chunk = lines[start - 1:end]
        body = "".join(f"{start + i:6d} | {line.rstrip()}\n" for i, line in enumerate(chunk))
        truncated = end < total
        if truncated:
            body += f"\n[truncated: {end}/{total} lines] Use grep to locate content, or read_file with offset={end + 1}."
        self.state.mark_read(p)
        return ToolResult.success(body, path=path, lines=total, truncated=truncated)


class WriteFileTool(Tool):
    name = "write_file"
    description = (
        "Create a NEW file. ONLY use when the file does not exist yet. "
        "NEVER use to overwrite an existing file — that is refused. Use edit_file for existing files."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path of the new file, relative to project root"},
            "content": {"type": "string", "description": "Full content of the file"},
        },
        "required": ["path", "content"],
    }

    def __init__(self, cwd: str, state: SessionState):
        self.cwd = cwd
        self.state = state

    def _abs(self, path: str) -> str:
        return os.path.normpath(os.path.join(self.cwd, normalize_write_path(path, self.cwd)))

    def guard(self, path: str, **kwargs) -> None:
        p = self._abs(path)
        ok, msg, sug = _check(p)
        if not ok:
            raise ToolError(msg, suggestion=sug)

    def execute(self, path: str, content: str) -> ToolResult:
        p = self._abs(path)
        content = _dedupe_md_tasks(content)
        ok, msg = safe_write(p, content, self.cwd, exist_ok=False)
        if not ok:
            return ToolResult.failure(msg, error="guarded")
        self.state.mark_read(p)
        return ToolResult.success(msg, path=path, chars=len(content))


def _dedupe_md_tasks(content: str) -> str:
    """0.8b models repeat task lines while generating markdown. Dedupe repeats."""
    import re as _re

    lines = content.splitlines()
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        m = _re.match(r"^\s*(?:- \[[ x]\]\s+(?:T\d+\.\s+)?|#{1,4}\s+T\d+\.\s*)(.+)$", line)
        if m:
            key = m.group(1).strip().lower()
            if key in seen:
                continue
            seen.add(key)
        out.append(line)
    return "\n".join(out)


def _check(p: str) -> tuple[bool, str, str | None]:
    if Path(p).exists():
        return False, (
            f"File '{p}' already exists. write_file refuses to overwrite existing files "
            "(prevents rewriting from scratch)."
        ), "Use edit_file for targeted changes after reading the file."
    return True, "", None


class EditFileTool(Tool):
    name = "edit_file"
    description = (
        "Edit an EXISTING file by replacing an exact text match. "
        "Requires the file to have been read this session. Use for targeted changes, NOT whole-file rewrites."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path of the file to edit"},
            "old_string": {"type": "string", "description": "Exact text to find (must match exactly)"},
            "new_string": {"type": "string", "description": "Replacement text"},
        },
        "required": ["path", "old_string", "new_string"],
    }

    def __init__(self, cwd: str, state: SessionState):
        self.cwd = cwd
        self.state = state

    def _abs(self, path: str) -> str:
        return os.path.normpath(os.path.join(self.cwd, normalize_write_path(path, self.cwd)))

    def guard(self, path: str, **kwargs) -> None:
        p = self._abs(path)
        if p not in self.state.read_files:
            raise ToolError(
                f"File '{path}' has not been read in this session. You MUST call read_file first "
                "(editing blind causes data loss)."
            )
        if not os.path.exists(p):
            raise ToolError(f"File '{path}' does not exist. Use write_file to create it.")

    def execute(self, path: str, old_string: str, new_string: str) -> ToolResult:
        p = self._abs(path)
        try:
            with open(p, "r", encoding="utf-8") as f:
                content = f.read()
        except OSError as e:
            return ToolResult.failure(f"Cannot read '{path}': {e}", error="os_error")
        count = content.count(old_string)
        if count == 0:
            snippet = old_string[:80].replace("\n", "\\n")
            return ToolResult.failure(
                f"old_string not found in '{path}'. The text must match EXACTLY. "
                f"Looked for: {snippet!r}. Re-read the file and copy exact content.",
                error="not_found",
                meta={"path": path},
            )
        if count > 1:
            return ToolResult.failure(
                f"old_string appears {count} times in '{path}'. Make the old_string longer/uniquier.",
                error="ambiguous",
                meta={"path": path},
            )
        new_content = content.replace(old_string, new_string)
        with open(p, "w", encoding="utf-8") as f:
            f.write(new_content)
        self.state.mark_read(p)
        return ToolResult.success(
            f"Edited {path}: replaced {len(old_string)} chars with {len(new_string)} chars.",
            path=path,
        )
