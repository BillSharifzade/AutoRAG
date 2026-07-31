"""Read-only access to KARAG's own source, for the assistant to consult.

The platform can answer questions about itself, and when it isn't sure it reads
the *current* code rather than reciting a stale summary. That only works if
"read the code" is a narrow, guarded capability rather than filesystem access:

* Every path is resolved and must land inside the repository root — no `..`
  escapes, no absolute paths, no symlinks pointing out of the tree.
* Secrets and runtime state are denied outright (`.env`, `*.db`, `.git/`), so
  "show me the config" can never surface an API key.
* Only source-ish extensions are readable, and reads are size-capped, so a
  single tool call cannot blow the model's context window.

Source code is *not* customer data — it carries no tenant and no data class, so
these skills are ``PUBLIC`` and available to every authenticated user. What the
codebase must never expose is credentials, which is what the deny-list is for.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# Directories never walked or read.
_DENY_DIRS = frozenset({
    ".git", ".venv", "venv", "node_modules", "__pycache__", ".next",
    ".pytest_cache", ".ruff_cache", "dist", "build", ".mypy_cache",
})

# Exact filenames never read, whatever their extension.
_DENY_FILES = frozenset({".env", ".env.local", ".env.production"})

# Suffixes never read: databases, binaries, media, lockfiles.
_DENY_SUFFIXES = frozenset({
    ".db", ".db-shm", ".db-wal", ".sqlite", ".sqlite3", ".pyc", ".so", ".dylib",
    ".dll", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".zip",
    ".gz", ".woff", ".woff2", ".ttf", ".mp3", ".mp4", ".bin", ".pem", ".key",
})

# Only these are considered "source" and are searchable/readable.
_ALLOW_SUFFIXES = frozenset({
    ".py", ".ts", ".tsx", ".js", ".jsx", ".css", ".sql", ".md", ".html",
    ".yml", ".yaml", ".toml", ".json", ".txt", ".sh", ".example", ".cfg", ".ini",
})

_MAX_READ_BYTES = 80_000
_MAX_SEARCH_HITS = 40


class PathNotAllowed(Exception):
    """A requested path is outside the repo or on the deny-list."""


@dataclass
class SearchHit:
    path: str
    line: int
    text: str

    def to_dict(self) -> dict:
        return {"path": self.path, "line": self.line, "text": self.text}


def _is_denied(path: Path) -> bool:
    if path.name in _DENY_FILES:
        return True
    if path.name.startswith(".env"):
        return True
    if path.suffix in _DENY_SUFFIXES:
        return True
    return any(part in _DENY_DIRS for part in path.parts)


class CodebaseIndex:
    """A guarded, read-only window onto the repository."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

    # ---- path safety -----------------------------------------------------

    def resolve(self, rel_path: str) -> Path:
        """Resolve a repo-relative path, refusing anything outside or denied.

        ``strict=False`` so a not-yet-existing file still resolves (the engineer
        flow needs to validate the target of a *new* file); existence is the
        caller's problem, containment is ours.
        """
        candidate = (self.root / rel_path.lstrip("/")).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise PathNotAllowed(f"{rel_path!r} is outside the repository") from exc
        if _is_denied(candidate.relative_to(self.root)):
            raise PathNotAllowed(f"{rel_path!r} is not readable (secret or build artefact)")
        return candidate

    def is_source(self, path: Path) -> bool:
        rel = path.relative_to(self.root)
        return path.suffix in _ALLOW_SUFFIXES and not _is_denied(rel)

    # ---- listing ---------------------------------------------------------

    def files(self, subdir: str = "") -> list[str]:
        """Repo-relative paths of every readable source file, sorted."""
        base = self.resolve(subdir) if subdir else self.root
        out: list[str] = []
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            try:
                rel = path.relative_to(self.root)
            except ValueError:
                continue
            if _is_denied(rel) or path.suffix not in _ALLOW_SUFFIXES:
                continue
            out.append(str(rel))
        return sorted(out)

    def tree(self, max_entries: int = 200) -> str:
        """A compact directory listing with per-file line counts."""
        lines: list[str] = []
        for rel in self.files()[:max_entries]:
            try:
                n = len((self.root / rel).read_text(encoding="utf-8", errors="replace").splitlines())
            except OSError:
                continue
            lines.append(f"{rel} ({n} lines)")
        return "\n".join(lines)

    # ---- reading ---------------------------------------------------------

    def read(self, rel_path: str, *, max_bytes: int = _MAX_READ_BYTES) -> str:
        path = self.resolve(rel_path)
        if not path.is_file():
            raise PathNotAllowed(f"{rel_path!r} does not exist")
        if not self.is_source(path):
            raise PathNotAllowed(f"{rel_path!r} is not a readable source file")
        data = path.read_text(encoding="utf-8", errors="replace")
        if len(data) > max_bytes:
            return data[:max_bytes] + f"\n… (truncated at {max_bytes} bytes)"
        return data

    def read_numbered(self, rel_path: str) -> str:
        """Source with line numbers — what an edit proposal needs to reference."""
        body = self.read(rel_path)
        return "\n".join(
            f"{i:5d}\t{line}" for i, line in enumerate(body.splitlines(), 1)
        )

    # ---- search ----------------------------------------------------------

    def search(
        self, query: str, *, subdir: str = "", max_hits: int = _MAX_SEARCH_HITS
    ) -> list[SearchHit]:
        """Case-insensitive regex search across readable source.

        A malformed pattern is treated as a literal rather than raising — the
        caller is a language model, and "search for `def foo(`" should work.
        """
        try:
            pattern = re.compile(query, re.IGNORECASE)
        except re.error:
            pattern = re.compile(re.escape(query), re.IGNORECASE)

        hits: list[SearchHit] = []
        for rel in self.files(subdir):
            try:
                text = (self.root / rel).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for lineno, line in enumerate(text.splitlines(), 1):
                if pattern.search(line):
                    hits.append(SearchHit(path=rel, line=lineno, text=line.strip()[:240]))
                    if len(hits) >= max_hits:
                        return hits
        return hits
