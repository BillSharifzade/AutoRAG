"""Guarded self-modification.

The gates, in order: role → protected path → untrusted provenance → human
review. Each is tested independently, because each on its own is what stops a
different failure mode.
"""

import subprocess
import tempfile
from pathlib import Path

import pytest

from karag.domain import Principal
from karag.engineer import (
    PENDING,
    CodeChangeRefused,
    CodeChangeService,
    FileEdit,
    GitWorkspace,
    InMemoryProposalStore,
    assert_may_edit,
    is_protected,
)
from karag.engineer.guard import MAX_FILES_PER_CHANGE
from karag.request_context import clear_request_context, mark_untrusted_content

ENGINEER = Principal("kit", "eng1", ("karag_engineer",))
ADMIN = Principal("koinoti", "admin1", ("admin",))
CEO = Principal("koinoti", "ceo1", ("ceo",))
OPERATOR = Principal("kit", "ops1", ("platform_admin",))


@pytest.fixture(autouse=True)
def _clean_context():
    clear_request_context()
    yield
    clear_request_context()


@pytest.fixture
def repo():
    """A throwaway git repo standing in for the platform's own checkout."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "karag").mkdir()
        (root / "karag" / "sample.py").write_text("VALUE = 1\n")
        (root / "README.md").write_text("# demo\n")
        for cmd in (
            ["git", "init", "-q"],
            ["git", "config", "user.email", "t@example.com"],
            ["git", "config", "user.name", "t"],
            ["git", "add", "-A"],
            ["git", "commit", "-q", "-m", "base"],
        ):
            subprocess.run(cmd, cwd=root, check=True, capture_output=True)
        yield root


@pytest.fixture
def service(repo):
    # `true` stands in for the test suite so these tests stay fast; the real
    # workspace runs pytest.
    ws = GitWorkspace(repo, test_command=["true"])
    return CodeChangeService(ws, InMemoryProposalStore())


# ---------- gate 1: role ----------


def test_only_the_engineer_role_may_propose():
    edits = [FileEdit(path="karag/sample.py", content="VALUE = 2\n")]
    for principal in (ADMIN, CEO, OPERATOR):
        with pytest.raises(CodeChangeRefused, match="karag_engineer"):
            assert_may_edit(principal, edits)
    assert_may_edit(ENGINEER, edits)  # does not raise


def test_a_tenant_admin_cannot_grant_themselves_the_role():
    """The role is platform-level; a customer's admin must never mint it."""
    from karag.errors import AccessDenied
    from karag.tenants import DirectoryService, InMemoryDirectory

    svc = DirectoryService(InMemoryDirectory())
    with pytest.raises(AccessDenied):
        svc.create_account(ADMIN, user_id="sneaky", roles=("karag_engineer",))
    with pytest.raises(AccessDenied):
        svc.create_account(CEO, user_id="sneaky", roles=("karag_engineer",))


def test_a_platform_admin_without_the_role_cannot_grant_it_either():
    from karag.errors import AccessDenied
    from karag.tenants import DirectoryService, InMemoryDirectory

    svc = DirectoryService(InMemoryDirectory())
    with pytest.raises(AccessDenied):
        svc.create_account(OPERATOR, user_id="e", roles=("karag_engineer",))

    both = Principal("kit", "boss", ("platform_admin", "karag_engineer"))
    account, _ = svc.create_account(both, user_id="e", roles=("karag_engineer",))
    assert account.roles == ("karag_engineer",)


# ---------- gate 2: protected paths ----------


@pytest.mark.parametrize("path", [
    "karag/rbac.py",
    "karag/tenants.py",
    "karag/api/security.py",
    "karag/api/jwt_auth.py",
    "karag/vectorstore/base.py",
    "karag/connectors/sql.py",
    "karag/engineer/guard.py",
    "karag/engineer/service.py",
    ".env",
    ".gitignore",
])
def test_security_critical_paths_are_protected(path):
    assert is_protected(path)
    with pytest.raises(CodeChangeRefused, match="protected"):
        assert_may_edit(ENGINEER, [FileEdit(path=path, content="# owned\n")])


def test_the_guard_cannot_be_edited_through_the_guard():
    """The loop that must not close: disable the check by changing the check."""
    with pytest.raises(CodeChangeRefused):
        assert_may_edit(
            ENGINEER,
            [FileEdit(path="karag/engineer/guard.py", content="def is_protected(p): return False\n")],
        )


def test_ordinary_source_is_editable():
    assert not is_protected("karag/orchestrator.py")
    assert_may_edit(ENGINEER, [FileEdit(path="karag/orchestrator.py", content="x = 1\n")])


def test_path_traversal_is_refused():
    for path in ("../../../etc/passwd", "karag/../../secrets.py"):
        with pytest.raises(CodeChangeRefused):
            assert_may_edit(ENGINEER, [FileEdit(path=path, content="x\n")])


def test_protection_survives_a_creative_path_spelling():
    for spelling in ("./karag/rbac.py", "karag//rbac.py", "/karag/rbac.py"):
        with pytest.raises(CodeChangeRefused):
            assert_may_edit(ENGINEER, [FileEdit(path=spelling, content="x\n")])


def test_non_source_file_types_are_refused():
    for path in ("karag.db", "secret.pem", "logo.png"):
        with pytest.raises(CodeChangeRefused):
            assert_may_edit(ENGINEER, [FileEdit(path=path, content="x\n")])


def test_a_change_cannot_touch_unbounded_files():
    edits = [FileEdit(path=f"karag/f{i}.py", content="x\n") for i in range(MAX_FILES_PER_CHANGE + 1)]
    with pytest.raises(CodeChangeRefused, match="at most"):
        assert_may_edit(ENGINEER, edits)


# ---------- gate 3: untrusted provenance ----------


def test_a_turn_carrying_untrusted_content_cannot_change_code():
    """Prompt injection: text in an uploaded PDF must not rewrite the platform."""
    mark_untrusted_content("retrieved documents")
    with pytest.raises(CodeChangeRefused, match="did not author"):
        assert_may_edit(
            ENGINEER,
            [FileEdit(path="karag/sample.py", content="x\n")],
            untrusted=("retrieved documents",),
        )


async def test_the_orchestrator_marks_retrieved_context(monkeypatch):
    from karag.config import Settings
    from karag.domain import DataClass
    from karag.factory import build_platform
    from karag.request_context import untrusted_sources

    plat = build_platform(Settings(generator="fake", embedder="fake", store="memory"))
    admin = Principal("koinoti", "a", ("admin",))
    await plat.ingestion.ingest_document(
        admin, title="Policy", text="Return within 14 days.", data_class=DataClass.PUBLIC
    )
    clear_request_context()
    await plat.orchestrator.ask(admin, "what is the returns policy?")
    assert "retrieved documents" in untrusted_sources()


# ---------- the workflow ----------


async def test_proposal_lands_on_a_branch_and_leaves_the_tree_untouched(service, repo):
    proposal = service.propose(
        ENGINEER,
        summary="bump the sample value",
        edits=[FileEdit(path="karag/sample.py", content="VALUE = 2\n")],
        model="claude-opus-4-8",
    )
    assert proposal.status == PENDING
    assert proposal.branch.startswith("karag/ai-")
    assert proposal.files_changed == ["karag/sample.py"]
    assert "VALUE = 2" in proposal.diff

    # the working tree the server runs from is unchanged
    assert (repo / "karag" / "sample.py").read_text() == "VALUE = 1\n"
    branch = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo,
        capture_output=True, text=True,
    ).stdout.strip()
    assert branch in {"master", "main"}


async def test_apply_merges_the_change(service, repo):
    proposal = service.propose(
        ENGINEER, summary="bump", edits=[FileEdit(path="karag/sample.py", content="VALUE = 2\n")]
    )
    service.apply(ENGINEER, proposal.id)
    assert (repo / "karag" / "sample.py").read_text() == "VALUE = 2\n"
    assert service.get(ENGINEER, proposal.id).status == "applied"


async def test_discard_leaves_nothing_behind(service, repo):
    proposal = service.propose(
        ENGINEER, summary="bump", edits=[FileEdit(path="karag/sample.py", content="VALUE = 2\n")]
    )
    service.discard(ENGINEER, proposal.id)
    assert (repo / "karag" / "sample.py").read_text() == "VALUE = 1\n"
    assert service.get(ENGINEER, proposal.id).status == "discarded"
    assert not GitWorkspace(repo).branch_exists(proposal.branch)


async def test_a_proposal_cannot_be_applied_twice(service):
    from karag.errors import KaragError

    proposal = service.propose(
        ENGINEER, summary="bump", edits=[FileEdit(path="karag/sample.py", content="VALUE = 2\n")]
    )
    service.apply(ENGINEER, proposal.id)
    with pytest.raises(KaragError, match="already applied"):
        service.apply(ENGINEER, proposal.id)


async def test_a_non_engineer_cannot_apply_someone_elses_proposal(service):
    """Applying re-checks the role rather than trusting the proposer's."""
    proposal = service.propose(
        ENGINEER, summary="bump", edits=[FileEdit(path="karag/sample.py", content="VALUE = 2\n")]
    )
    with pytest.raises(CodeChangeRefused):
        service.apply(ADMIN, proposal.id)
    with pytest.raises(CodeChangeRefused):
        service.list(CEO)


async def test_failing_tests_are_recorded_not_hidden(repo):
    ws = GitWorkspace(repo, test_command=["false"])  # always fails
    svc = CodeChangeService(ws, InMemoryProposalStore())
    proposal = svc.propose(
        ENGINEER, summary="bad change",
        edits=[FileEdit(path="karag/sample.py", content="VALUE = 2\n")],
    )
    assert proposal.tests_passed is False
    # It is still stored for review — a human sees the red result and decides.
    assert proposal.status == PENDING


async def test_proposing_refuses_on_a_dirty_tree(service, repo):
    from karag.engineer import GitError

    (repo / "karag" / "sample.py").write_text("VALUE = 99\n")
    with pytest.raises(GitError, match="uncommitted"):
        service.propose(
            ENGINEER, summary="x",
            edits=[FileEdit(path="karag/sample.py", content="VALUE = 2\n")],
        )


# ---------- the skill wrapper ----------


async def test_skill_reports_a_refusal_as_data(service):
    from karag.engineer.skills import engineer_skills

    skill = engineer_skills(service)[0]
    result = await skill.handler(
        ENGINEER, {"summary": "own the rbac", "files": [{"path": "karag/rbac.py", "content": "x"}]}
    )
    assert result.data["status"] == "refused"
    assert "protected" in result.data["reason"]


async def test_skill_is_invisible_without_the_role():
    from karag.config import Settings
    from karag.factory import build_platform

    plat = build_platform(Settings(generator="fake", embedder="fake", store="memory"))
    for principal in (ADMIN, CEO, OPERATOR):
        names = {s.name for s in plat.registry.visible_for(principal)}
        assert "propose_code_change" not in names
    assert "propose_code_change" in {
        s.name for s in plat.registry.visible_for(ENGINEER)
    }
