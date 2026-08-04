from __future__ import annotations

"""Minimal TUI: prompt_toolkit-based chat with streaming and Y/N confirmations.

Deferred: full Textual UI (STORIES F19). This is the MVP shell.
"""

import sys
from typing import Callable

from rich.console import Console

console = Console(highlight=False)


def _has_tty() -> bool:
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except Exception:
        return False


class MinimalUI:
    def __init__(self):
        self.history = None
        self.session = None
        self._tty = _has_tty()

    def start(self) -> None:
        if not self._tty:
            return
        try:
            from prompt_toolkit import PromptSession
            from prompt_toolkit.history import InMemoryHistory

            self.history = InMemoryHistory()
            self.session = PromptSession(history=self.history)
        except Exception:
            self._tty = False

    # ---------------------------------------------------------------- input
    def prompt(self, header: str = "") -> str | None:
        if header:
            console.print(header, style="bold cyan")
        if self.session is not None:
            try:
                text = self.session.prompt("you> ")
                return text.strip()
            except (KeyboardInterrupt, EOFError):
                return None
        try:
            text = input("you> ")
            return text.strip()
        except (KeyboardInterrupt, EOFError):
            return None

    # ---------------------------------------------------------------- output
    def user(self, text: str) -> None:
        console.print(f"[bold green]you>[/] {text}")

    def assistant(self, text: str) -> None:
        if not text.strip():
            return
        console.print(f"[bold blue]agent>[/] {text}")

    def stream_chunk(self, chunk: str) -> None:
        console.print(chunk, end="", style="blue")

    def system(self, text: str) -> None:
        console.print(f"[dim]- {text}[/]")

    def tool(self, text: str) -> None:
        console.print(f"[yellow]tool> {text}[/]")

    def judge(self, text: str) -> None:
        console.print(f"[magenta]judge> {text}[/]")

    def error(self, text: str) -> None:
        console.print(f"[red]x {text}[/]")

    def confirm(self, question: str, default: str = "Y") -> str:
        if self.session is not None:
            try:
                answer = self.session.prompt(f"? {question} ")
            except (KeyboardInterrupt, EOFError):
                return default
        else:
            try:
                answer = input(f"? {question} ")
            except (KeyboardInterrupt, EOFError):
                return default
        if not answer.strip():
            return default
        return answer.strip()
