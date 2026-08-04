from __future__ import annotations

from tools.base import Tool
from tools.bash_tools import BashTool, GlobTool, GrepTool, LsTool
from tools.file_tools import EditFileTool, ReadFileTool, WriteFileTool
from tools.guards.state import SessionState
from tools.registry import get_registry


def register_builtin_tools(cwd: str, state: SessionState, context: dict | None = None) -> None:
    reg = get_registry()
    reg.register(ReadFileTool(cwd, state, context))
    reg.register(WriteFileTool(cwd, state))
    reg.register(EditFileTool(cwd, state))
    reg.register(BashTool(cwd, state))
    reg.register(LsTool(cwd))
    reg.register(GlobTool(cwd))
    reg.register(GrepTool(cwd))
