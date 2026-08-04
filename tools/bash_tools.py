from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from tools.base import Tool, ToolError, ToolResult
from tools.guards.permission import is_safe_bash, set_extra_allow
from tools.guards.state import SessionState

_EXTRA_ALLOW_ENV = "LITTLE_AGENT_BASH_ALLOW"


class BashTool(Tool):
    name = "bash"
    description = (
        "Run a terminal command in the project directory. Read-only commands are preferred. "
        "Never use this to write files (redirects/tee are blocked) — use write_file/edit_file instead. "
        "For file edits NEVER use sed/awk — use edit_file."
    )
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "The shell command to run. Windows: powershell.exe"},
        },
        "required": ["command"],
    }

    def __init__(self, cwd: str, state: SessionState, timeout: int = 90):
        self.cwd = cwd
        self.state = state
        self.timeout = timeout
        env = os.environ.get(_EXTRA_ALLOW_ENV)
        if env:
            set_extra_allow(env.split(","))

    def guard(self, command: str, **kwargs) -> None:
        safe, reason = is_safe_bash(command)
        if not safe:
            raise ToolError(f"[permission-gate] {reason}")

    def execute(self, command: str) -> ToolResult:
        start = time.monotonic()
        try:
            proc = subprocess.run(
                command,
                shell=True,
                cwd=self.cwd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired:
            return ToolResult.failure(f"Command timed out after {self.timeout}s.", error="timeout", meta={"command": command})
        out = (proc.stdout or "") + (proc.stderr or "")
        if not out.strip():
            out = "(no output)"
        elapsed = time.monotonic() - start
        body = f"$ {command}\n{out}"
        if proc.returncode != 0:
            body += f"\n[exit code: {proc.returncode}]"
            return ToolResult.failure(body, error="exit_nonzero", meta={"command": command, "elapsed": round(elapsed, 2)})
        return ToolResult.success(body, command=command, elapsed=round(elapsed, 2))


class LsTool(Tool):
    name = "ls"
    description = "List files and folders in a directory. Use to see project structure."
    parameters = {
        "type": "object",
        "properties": {"path": {"type": "string", "description": "Directory path. Default: project root."}},
        "required": [],
    }

    def __init__(self, cwd: str):
        self.cwd = cwd

    def execute(self, path: str | None = None) -> ToolResult:
        target = os.path.normpath(os.path.join(self.cwd, path)) if path else self.cwd
        if not os.path.exists(target):
            return ToolResult.failure(f"Path '{target}' does not exist.", error="not_found")
        if not os.path.isdir(target):
            return ToolResult.failure(f"'{target}' is not a directory.", error="not_a_dir")
        try:
            entries = sorted(os.listdir(target))
        except OSError as e:
            return ToolResult.failure(f"Cannot list '{target}': {e}", error="os_error")
        lines = []
        for name in entries:
            if name.startswith("."):
                continue  # hidden artifacts (.tiny-agent, .git) are not shown to the model
            full = os.path.join(target, name)
            suffix = "/" if os.path.isdir(full) else ""
            lines.append(f"{name}{suffix}")
        return ToolResult.success("\n".join(lines) if lines else "(empty directory)", path=target)


class GlobTool(Tool):
    name = "glob"
    description = "Search for files recursively using glob patterns. Supports ** for recursive. Example: '**/*.py'"
    parameters = {
        "type": "object",
        "properties": {"pattern": {"type": "string", "description": "Glob pattern relative to project root"}},
        "required": ["pattern"],
    }

    def __init__(self, cwd: str):
        self.cwd = cwd

    def execute(self, pattern: str) -> ToolResult:
        import glob as glob_mod

        full = os.path.join(self.cwd, pattern)
        matches = [p.replace("\\", "/") for p in sorted(glob_mod.glob(full, recursive=True)) if os.path.isfile(p)]
        if len(matches) > 200:
            shown = matches[:200]
            return ToolResult.success("\n".join(shown) + f"\n... {len(matches) - 200} more results", truncated=True)
        return ToolResult.success("\n".join(matches) if matches else "(no matches)", count=len(matches))


class GrepTool(Tool):
    name = "grep"
    description = "Search file contents using regular expressions. Use to locate code before reading it."
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Regex pattern"},
            "path": {"type": "string", "description": "Directory or file to search. Default: project root"},
            "include": {"type": "string", "description": "File glob to filter, e.g. '*.py'"},
        },
        "required": ["pattern"],
    }

    def __init__(self, cwd: str):
        self.cwd = cwd

    def execute(self, pattern: str, path: str | None = None, include: str | None = None) -> ToolResult:
        import re

        import fnmatch

        target = os.path.normpath(os.path.join(self.cwd, path)) if path else self.cwd
        rx = re.compile(pattern)
        results = []
        walked = 0

        def walk(directory: str) -> None:
            nonlocal walked
            try:
                items = sorted(os.listdir(directory))
            except OSError:
                return
            for item in items:
                full = os.path.join(directory, item)
                if item in (".git", ".venv", "__pycache__", "node_modules", ".tiny-agent", ".tiny-tools"):
                    continue
                if os.path.isdir(full):
                    walk(full)
                elif os.path.isfile(full):
                    walked += 1
                    if include and not fnmatch.fnmatch(item, include):
                        continue
                    try:
                        with open(full, "r", encoding="utf-8", errors="ignore") as f:
                            for lineno, line in enumerate(f, 1):
                                if rx.search(line):
                                    rel = os.path.relpath(full, self.cwd)
                                    results.append(f"{rel}:{lineno}: {line.rstrip()[:200]}")
                                    if len(results) >= 100:
                                        return
                    except OSError:
                        pass

        walk(target)
        if not results:
            return ToolResult.success("(no matches)", walked=walked)
        return ToolResult.success("\n".join(results), walked=walked, truncated=len(results) >= 100)
