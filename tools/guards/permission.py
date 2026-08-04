from __future__ import annotations

"""Bash permission gate: whitelist prefixes, chain splitting, shell-write detection."""

import re

BUILTIN_SAFE_PREFIXES: tuple[str, ...] = (
    "ls", "cat", "head", "tail", "wc", "pwd", "echo",
    "git log", "git status", "git diff", "git show", "git branch", "git rev-parse",
    "find ", "grep ", "rg ",
    "python ", "python3 ", "py ",
    "node ", "npm ", "pip ", "pip3 ", "cargo ", "go ",
    "cp ", "mv ", "mkdir ", "touch ", "type ",
    "dir ", "where ", "cls", "clear",
)

# rm, sudo, chmod, chown, chgrp, kill, shutdown, format, del, erase
BLOCKED_PREFIXES: tuple[str, ...] = ("rm", "sudo", "chmod", "chown", "chgrp", "kill", "shutdown", "format", "del ", "erase")

CHAIN_SEPARATORS: tuple[str, ...] = ("&&", "||", ";", "|", "\n")

RESERVED_DEVICES = tuple(f"COM{i}" for i in range(1, 10)) + tuple(f"LPT{i}" for i in range(1, 10)) + ("CON", "PRN", "AUX", "NUL")

EXTRA_ALLOW: list[str] = []


def set_extra_allow(prefixes: list[str]) -> None:
    global EXTRA_ALLOW
    EXTRA_ALLOW = [p for p in prefixes if p.strip()]


def _strip_quotes(cmd: str) -> str:
    return cmd.strip().strip('"\'')


def _find_write_targets(cmd: str) -> list[str]:
    """Detect shell file writes: >, >>, tee, dd of=. Quote-aware.
    Redirect descriptors (2>&1, 1>&2, 2>/dev/null) are NOT file writes."""
    import re as _re

    targets: list[str] = []
    in_single = in_double = False
    # strip heredoc bodies first
    cmd = _re.sub(r"<<\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?.*?\n\s*\1\s*$", "", cmd, flags=_re.S)
    tokens: list[str] = []
    buf = ""
    i = 0
    while i < len(cmd):
        c = cmd[i]
        if c == "'" and not in_double:
            in_single = not in_single
        elif c == '"' and not in_single:
            in_double = not in_double
        elif c in ">" and not in_single and not in_double:
            # descriptor redirect like 2>&1 or 1>&2 or 2>>file — not a write
            prefix = cmd[max(0, i - 3):i]
            if _re.search(r"\d\s*>\s*&?\s*\d?\s*$", prefix) or _re.match(r"&\d?\s*$", prefix):
                i += 1
                continue
            if buf.strip():
                tokens.append(buf.strip())
                buf = ""
            # read target
            j = i + 1
            while j < len(cmd) and cmd[j] in "> \t":
                j += 1
            target = ""
            while j < len(cmd) and cmd[j] not in " \t&|;\n":
                target += cmd[j]
                j += 1
            if target:
                targets.append(target)
            i = j
            continue
        elif c in "&|;" and not in_single and not in_double:
            if buf.strip():
                tokens.append(buf.strip())
                buf = ""
        else:
            buf += c
        i += 1
    if buf.strip():
        tokens.append(buf.strip())
    # check tee / dd of=
    for t in tokens:
        low = t.strip().lower()
        if low.startswith("tee ") and len(low.split()) > 1:
            targets.append(low.split()[1].strip('"\'><'))
        m = _re.search(r"dd\s+.*\bof=([^\s]+)", low)
        if m:
            targets.append(m.group(1).strip('"\'><'))
    return targets


def _is_non_destructive(target: str) -> bool:
    t = target.lower()
    return t.startswith("/dev/null") or t in ("nul",) or t.startswith("/dev/std") or t.startswith("2>") or t == ""


def is_safe_bash(command: str) -> tuple[bool, str | None]:
    """Returns (safe, reason_if_blocked)."""
    cmd = command.strip()
    if not cmd:
        return False, "Empty command."
    # block reserved device names anywhere
    upper = cmd.upper()
    for dev in RESERVED_DEVICES:
        for m in re.finditer(rf"\b{dev}(\.\w+)?\b", upper):
            if m.start() > 0 and (cmd[m.start() - 1].isalnum()):
                continue
            # only block if it's a write target
            if any(t.upper().startswith(dev) for t in _find_write_targets(cmd)):
                return False, f"Write to reserved device '{dev}' is blocked."
    # shell writes always blocked (except /dev/null etc.)
    for t in _find_write_targets(cmd):
        if not _is_non_destructive(t):
            return False, f"Shell write to '{t}' detected. Use the write_file/edit_file tools instead."
    # chain splitting: every segment must pass
    segments = re.split(r"(?:&&|\|\||;|\||\n)", cmd)
    for seg in segments:
        seg = _strip_quotes(seg)
        if not seg:
            continue
        low = seg.lower()
        for blocked in BLOCKED_PREFIXES:
            if low.startswith(blocked):
                return False, f"Command '{seg.strip()[:60]}' uses blocked prefix '{blocked}'."
        if low.startswith("cd "):
            return False, (
                "Do NOT use 'cd'. Commands already run in the project directory. "
                "Run the command directly (e.g. 'python -m pytest -v' instead of 'cd /tmp && python -m pytest')."
            )
        safe = any(low.startswith(p) for p in BUILTIN_SAFE_PREFIXES) or any(low.startswith(p) for p in EXTRA_ALLOW)
        if not safe:
            return False, (
                f"Command '{seg.strip()[:60]}' is not on the allowlist. "
                "Allowed prefixes: " + ", ".join(BUILTIN_SAFE_PREFIXES[:8]) + ", ... "
                "Use LITTLE_AGENT_BASH_ALLOW to extend."
            )
    return True, None
