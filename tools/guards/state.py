from __future__ import annotations

"""Session-level state shared by guards: read-before-edit tracking, loop detection, context usage."""

import hashlib
import json
from collections import deque


class SessionState:
    def __init__(self) -> None:
        self.read_files: set[str] = set()
        self.last_tool_calls: deque[tuple[str, str]] = deque(maxlen=8)
        self.completed_writes: set[tuple[str, str]] = set()
        self.loop_count = 0
        self.turn_count = 0
        self.code_offers = 0

    def record_tool_call(self, name: str, args: dict) -> bool:
        """Window-based loop detection: same call seen 3+ times in the last 8 calls."""
        arg_hash = hashlib.md5(json.dumps(args, sort_keys=True).encode()).hexdigest()[:8]
        key = (name, arg_hash)
        self.last_tool_calls.append(key)
        count = sum(1 for k in self.last_tool_calls if k == key)
        if count >= 3:
            self.loop_count += 1
            return True
        return False

    def mark_write_done(self, name: str, args: dict) -> None:
        arg_hash = hashlib.md5(json.dumps(args, sort_keys=True).encode()).hexdigest()[:8]
        self.completed_writes.add((name, arg_hash))

    def is_write_done(self, name: str, args: dict) -> bool:
        arg_hash = hashlib.md5(json.dumps(args, sort_keys=True).encode()).hexdigest()[:8]
        return (name, arg_hash) in self.completed_writes

    def mark_read(self, path: str) -> None:
        self.read_files.add(path)

    def mark_edited(self, path: str) -> None:
        self.read_files.add(path)

    def reset_loops(self) -> None:
        self.last_tool_calls.clear()
        self.loop_count = 0


def estimate_tokens(text: str) -> int:
    """Chars / 3.5 — rough token estimate (English-heavy)."""
    return max(1, len(text) // 3)
