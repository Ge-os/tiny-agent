from __future__ import annotations

"""RAG: BM25 retrieval over docs/ (and optionally the project).

Auto-detects the shell reference by OS:
  - Windows → powershell.md (or cmd.md if present)
  - linux/mac → bash.md
"""

import os
import platform
import re
import sys
from pathlib import Path
from typing import Any

from tools.guards.state import estimate_tokens

MAX_DOCS_TOKENS = 600


class BM25Index:
    """Tiny BM25 (Okapi) — no external deps."""

    def __init__(self) -> None:
        self.docs: list[str] = []
        self.tokens: list[list[str]] = []
        self.idf: dict[str, float] = {}
        self.avgdl = 1.0
        self.k1 = 1.5
        self.b = 0.75

    def _tok(self, text: str) -> list[str]:
        return re.findall(r"[a-zA-Z0-9_\-\.]+", text.lower())

    def add(self, text: str) -> int:
        idx = len(self.docs)
        self.docs.append(text)
        toks = self._tok(text)
        self.tokens.append(toks)
        return idx

    def build(self) -> None:
        n = len(self.docs)
        if not n:
            return
        df: dict[str, int] = {}
        for toks in self.tokens:
            for t in set(toks):
                df[t] = df.get(t, 0) + 1
        for t, d in df.items():
            self.idf[t] = max(0.1, (n - d + 0.5) / (d + 0.5) + 1)
        self.avgdl = sum(len(t) for t in self.tokens) / n

    def search(self, query: str, top_k: int = 3) -> list[tuple[str, float]]:
        q = self._tok(query)
        if not q or not self.docs:
            return []
        scored: list[tuple[int, float]] = []
        for i, toks in enumerate(self.tokens):
            dl = len(toks)
            score = 0.0
            for t in q:
                tf = toks.count(t)
                if tf == 0:
                    continue
                idf = self.idf.get(t, 1.0)
                score += idf * (tf * (self.k1 + 1)) / (tf + self.k1 * (1 - self.b + self.b * dl / self.avgdl))
            if score > 0:
                scored.append((i, score))
        scored.sort(key=lambda x: -x[1])
        return [(self.docs[i], s) for i, s in scored[:top_k]]


class Rag:
    def __init__(self, docs_root: str | None = None):
        self.docs_root = Path(docs_root) if docs_root else Path(__file__).parent.parent / "docs"
        self._indexes: dict[str, BM25Index] = {}
        self._built = False

    # ------------------------------------------------------------------ indexing
    def _load_collection(self, name: str) -> BM25Index:
        """Collection = docs/<name>.md file OR docs/<name>/ folder of md files."""
        if name in self._indexes:
            return self._indexes[name]
        idx = BM25Index()
        p = self.docs_root / f"{name}.md"
        if p.exists():
            idx.add(p.read_text(encoding="utf-8", errors="replace"))
        folder = self.docs_root / name
        if folder.is_dir():
            for md in sorted(folder.glob("*.md"))[:10]:
                idx.add(md.read_text(encoding="utf-8", errors="replace"))
        idx.build()
        self._indexes[name] = idx
        return idx

    def build_all(self) -> None:
        if self._built:
            return
        for f in self.docs_root.glob("*.md"):
            self._load_collection(f.stem)
        for d in self.docs_root.iterdir():
            if d.is_dir() and not d.name.startswith("."):
                self._load_collection(d.name)
        self._built = True

    # ------------------------------------------------------------------ shell detection
    @staticmethod
    def shell_collection() -> str:
        if sys.platform.startswith("win"):
            return "powershell"
        return "bash"

    def shell_ref(self, task: str | None = None) -> str:
        """Auto-pull shell reference docs relevant to the task (bash on unix, powershell on win)."""
        name = self.shell_collection()
        idx = self._load_collection(name)
        if not idx.docs:
            return ""
        query = task or ""
        if query:
            results = idx.search(query, top_k=2)
        else:
            results = [(idx.docs[0], 1.0)]
        chunks: list[str] = []
        total = 0
        for text, _ in results:
            chunk = self._trim_around_query(text, query, limit=300)
            chunks.append(chunk)
            total += estimate_tokens(chunk)
            if total > MAX_DOCS_TOKENS:
                break
        return "\n---\n".join(chunks) if chunks else ""

    @staticmethod
    def _trim_around_query(text: str, query: str, limit: int) -> str:
        if not query:
            return text[: limit * 3]
        q_tokens = set(re.findall(r"[a-zA-Z0-9_]+", query.lower()))
        lines = text.splitlines()
        best_idx, best_score = 0, 0
        for i, line in enumerate(lines):
            score = sum(1 for t in q_tokens if t.lower() in line.lower())
            if score > best_score:
                best_score, best_idx = score, i
        start = max(0, best_idx - 4)
        chunk = "\n".join(lines[start:start + 40])
        if best_score == 0:
            chunk = text[: limit * 3]
        return chunk[: limit * 3]

    # ------------------------------------------------------------------ generic search
    def retrieve(self, query: str, collection: str = "", top_k: int = 3) -> str:
        self.build_all()
        name = collection or self.shell_collection()
        idx = self._load_collection(name)
        results = idx.search(query, top_k=top_k)
        parts = []
        total = 0
        for text, _ in results:
            chunk = self._trim_around_query(text, query, limit=200)
            parts.append(chunk)
            total += estimate_tokens(chunk)
            if total > MAX_DOCS_TOKENS:
                break
        return "\n---\n".join(parts)

    # ------------------------------------------------------------------ project indexing (stub, TASKS T49)
    def index_project(self, root: str) -> None:
        """Index project source files for code retrieval (deferred to phase 3)."""
