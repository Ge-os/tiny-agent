from __future__ import annotations

"""Write guard: path normalization, reserved device names, existing-file protection."""

import os
import re
from pathlib import Path

from tools.guards.permission import RESERVED_DEVICES


def normalize_write_path(path: str, cwd: str) -> str:
    """Small models write '/foo.md' meaning project-root-relative. Normalize to cwd."""
    if path.startswith("/") and not path.startswith("//"):
        return str(Path(cwd) / path.lstrip("/"))
    return path


def is_reserved_device(path: str) -> bool:
    name = Path(path).name
    stem = name.split(".")[0].upper() if "." in name else name.upper()
    return stem in RESERVED_DEVICES


def check_write_ok(path: str, cwd: str, exist_ok: bool = False) -> tuple[bool, str, str | None]:
    """Returns (ok, message, suggestion)."""
    if is_reserved_device(path):
        return False, f"Write to reserved device name '{path}' is blocked.", None
    p = Path(path)
    if p.exists() and not exist_ok:
        return (
            False,
            f"File '{path}' already exists. You must NOT overwrite an existing file with write_file.",
            "Use edit_file for targeted changes, or choose a different path.",
        )
    return True, "", None


def safe_write(path: str, content: str, cwd: str, exist_ok: bool = False) -> tuple[bool, str]:
    ok, msg, sug = check_write_ok(path, cwd, exist_ok)
    if not ok:
        return False, msg + (" " + sug if sug else "")
    parent = Path(path).parent
    if str(parent) not in ("", "."):
        parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return True, f"Wrote {len(content)} chars to {path}"


def is_binary(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            chunk = f.read(8192)
        return b"\x00" in chunk
    except OSError:
        return False
