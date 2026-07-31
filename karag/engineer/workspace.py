"""Git mechanics for a proposed change: branch, write, test, diff, apply.

A proposal never touches the working tree the server is running from. It is
committed on its own branch, the test suite runs against it, and the checkout
returns to where it started — so a failed or malicious proposal leaves nothing
behind but a branch someone can delete.

Applying is a separate, human-triggered step that merges that branch back.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from ..errors import KaragError


class GitError(KaragError):
    """A git command failed."""


@dataclass
class TestOutcome:
    passed: bool
    summary: str
    output: str = ""

    def to_dict(self) -> dict:
        return {"passed": self.passed, "summary": self.summary, "output": self.output[-4000:]}


@dataclass
class BranchResult:
    branch: str
    diff: str
    files_changed: list[str] = field(default_factory=list)
    insertions: int = 0
    deletions: int = 0
    tests: TestOutcome | None = None


class GitWorkspace:
    """Thin, explicit wrapper over the git CLI rooted at the repository."""

    # Commits are attributed to the platform, not to a human who didn't write them.
    AUTHOR_NAME = "KARAG engineer (AI)"
    AUTHOR_EMAIL = "karag-engineer@koinoti.local"

    def __init__(self, root: str | Path, *, test_command: list[str] | None = None) -> None:
        self.root = Path(root).resolve()
        self.test_command = test_command or [".venv/bin/python", "-m", "pytest", "-q"]

    # ---- plumbing --------------------------------------------------------

    def _git(self, *args: str, check: bool = True, timeout: int = 120) -> str:
        proc = subprocess.run(
            ["git", *args], cwd=self.root, capture_output=True, text=True, timeout=timeout
        )
        if check and proc.returncode != 0:
            raise GitError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
        return proc.stdout

    def is_repo(self) -> bool:
        try:
            return self._git("rev-parse", "--is-inside-work-tree").strip() == "true"
        except (GitError, FileNotFoundError, subprocess.SubprocessError):
            return False

    def current_branch(self) -> str:
        return self._git("rev-parse", "--abbrev-ref", "HEAD").strip()

    def is_clean(self) -> bool:
        return not self._git("status", "--porcelain").strip()

    def branch_exists(self, branch: str) -> bool:
        proc = subprocess.run(
            ["git", "rev-parse", "--verify", branch],
            cwd=self.root, capture_output=True, text=True,
        )
        return proc.returncode == 0

    # ---- proposing -------------------------------------------------------

    def propose(
        self,
        branch: str,
        edits: list[tuple[str, str]],
        message: str,
        *,
        run_tests: bool = True,
    ) -> BranchResult:
        """Commit ``edits`` on a fresh ``branch``, test it, and return the diff.

        Always restores the original branch, including on failure — the running
        server must never be left on a proposal branch.
        """
        if not self.is_repo():
            raise GitError(
                "this project is not a git repository; code proposals need version "
                "control so a change can be reviewed and rolled back"
            )
        if not self.is_clean():
            raise GitError(
                "the working tree has uncommitted changes; commit or stash them "
                "before proposing an AI change so the diff is unambiguous"
            )

        base = self.current_branch()
        self._git("checkout", "-b", branch)
        try:
            for rel_path, content in edits:
                target = self.root / rel_path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
                self._git("add", "--", rel_path)

            self._git(
                "-c", f"user.name={self.AUTHOR_NAME}",
                "-c", f"user.email={self.AUTHOR_EMAIL}",
                "commit", "-q", "-m", message,
            )
            diff = self._git("diff", f"{base}...{branch}")
            stat = self._git("diff", "--numstat", f"{base}...{branch}")
            files, ins, dels = [], 0, 0
            for line in stat.splitlines():
                parts = line.split("\t")
                if len(parts) == 3:
                    added, removed, path = parts
                    files.append(path)
                    ins += int(added) if added.isdigit() else 0
                    dels += int(removed) if removed.isdigit() else 0

            tests = self.run_tests() if run_tests else None
            return BranchResult(
                branch=branch, diff=diff, files_changed=files,
                insertions=ins, deletions=dels, tests=tests,
            )
        finally:
            # Whatever happened, put the server's checkout back.
            self._git("checkout", "-q", base, check=False)

    def run_tests(self, timeout: int = 600) -> TestOutcome:
        try:
            proc = subprocess.run(
                self.test_command, cwd=self.root, capture_output=True,
                text=True, timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return TestOutcome(False, f"test run exceeded {timeout}s")
        except FileNotFoundError:
            return TestOutcome(False, f"test command not found: {self.test_command[0]}")
        output = (proc.stdout + proc.stderr).strip()
        summary = next(
            (ln for ln in reversed(output.splitlines())
             if "passed" in ln or "failed" in ln or "error" in ln),
            output.splitlines()[-1] if output.splitlines() else "no output",
        )
        return TestOutcome(proc.returncode == 0, summary.strip(), output)

    # ---- applying / discarding -------------------------------------------

    def apply(self, branch: str) -> str:
        """Fast-forward-or-merge the proposal into the current branch."""
        if not self.branch_exists(branch):
            raise GitError(f"branch {branch} no longer exists")
        if not self.is_clean():
            raise GitError("working tree is dirty; commit or stash before applying")
        return self._git("merge", "--no-ff", "-m", f"Apply AI proposal {branch}", branch)

    def discard(self, branch: str) -> None:
        if self.branch_exists(branch):
            self._git("branch", "-D", branch, check=False)

    def show_diff(self, branch: str, base: str = "HEAD") -> str:
        if not self.branch_exists(branch):
            raise GitError(f"branch {branch} no longer exists")
        return self._git("diff", f"{base}...{branch}")
