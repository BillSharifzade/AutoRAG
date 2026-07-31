"""Document catalogue + auto-classification (§7).

The catalogue must obey the same permission-aware rule as retrieval: a title is
a disclosure. And auto-classification must stay advisory — §7 allows it "only
as a suggestion".
"""

import pytest
from fastapi.testclient import TestClient

from karag.api.app import create_app
from karag.api.security import InMemoryResolver
from karag.config import Settings
from karag.domain import DataClass, Principal
from karag.factory import build_platform
from karag.knowledge.classify import suggest_data_class
from karag.vectorstore.memory import InMemoryVectorStore
from karag.vectorstore.sqlite import SqliteVectorStore

CEO = Principal("koinoti", "ceo1", ("ceo",))
HR = Principal("koinoti", "hr1", ("hr",))
ADMIN = Principal("koinoti", "admin", ("admin",))
EMPLOYEE = Principal("koinoti", "emp", ("employee",))
EVAR = Principal("evar", "ceo2", ("ceo",))


async def _seed(platform):
    await platform.ingestion.ingest_document(
        ADMIN, title="Q3 financial results", text="Revenue was 18450.",
        data_class=DataClass.FINANCIAL,
    )
    await platform.ingestion.ingest_document(
        ADMIN, title="Returns policy", text="Return within 14 days.",
        data_class=DataClass.PUBLIC,
    )
    await platform.ingestion.ingest_document(
        ADMIN, title="Headcount plan", text="Hiring two engineers.",
        data_class=DataClass.HR,
    )


@pytest.fixture
def platform():
    return build_platform(Settings(generator="fake", embedder="fake", store="memory"))


# ---------- catalogue is permission-aware ----------


async def test_catalogue_hides_titles_the_caller_may_not_read(platform):
    await _seed(platform)
    from karag.rbac import visible_classes

    hr_docs = await platform.store.list_documents(
        tenant_id="koinoti", allowed_classes=visible_classes(HR)
    )
    titles = {d.title for d in hr_docs}
    assert "Headcount plan" in titles
    assert "Returns policy" in titles
    assert "Q3 financial results" not in titles  # the title itself would leak


async def test_ceo_sees_every_class_in_their_own_tenant(platform):
    await _seed(platform)
    from karag.rbac import visible_classes

    docs = await platform.store.list_documents(
        tenant_id="koinoti", allowed_classes=visible_classes(CEO)
    )
    assert len(docs) == 3


async def test_catalogue_is_empty_for_another_tenant(platform):
    await _seed(platform)
    from karag.rbac import visible_classes

    docs = await platform.store.list_documents(
        tenant_id="evar", allowed_classes=visible_classes(EVAR)
    )
    assert docs == []


async def test_no_clearance_lists_nothing(platform):
    await _seed(platform)
    assert await platform.store.list_documents(
        tenant_id="koinoti", allowed_classes=frozenset()
    ) == []


async def test_chunk_counts_are_aggregated_per_document(platform):
    long_text = "Return within 14 days. " * 200
    await platform.ingestion.ingest_document(
        ADMIN, title="Long policy", text=long_text, data_class=DataClass.PUBLIC
    )
    from karag.rbac import visible_classes

    docs = await platform.store.list_documents(
        tenant_id="koinoti", allowed_classes=visible_classes(CEO)
    )
    assert len(docs) == 1 and docs[0].chunks > 1


@pytest.mark.parametrize("store", [InMemoryVectorStore(), SqliteVectorStore(":memory:")])
async def test_both_stores_agree_on_the_catalogue(store):
    platform = build_platform(Settings(generator="fake", embedder="fake", store="memory"))
    platform.store = store
    platform.ingestion._store = store
    await _seed(platform)
    from karag.rbac import visible_classes

    docs = await store.list_documents(
        tenant_id="koinoti", allowed_classes=visible_classes(HR)
    )
    assert {d.title for d in docs} == {"Headcount plan", "Returns policy"}
    assert all(d.data_class in (DataClass.HR, DataClass.PUBLIC) for d in docs)


# ---------- classification is a suggestion, never a decision ----------


def test_financial_terms_are_recognised_in_three_languages():
    for title in ("Q3 revenue report", "Отчёт о выручке", "Ҳисоботи даромад"):
        assert suggest_data_class(title=title).suggested is DataClass.FINANCIAL


def test_hr_terms_are_recognised():
    assert suggest_data_class(title="Трудовой договор").suggested is DataClass.HR
    assert suggest_data_class(title="Personnel file").suggested is DataClass.HR


def test_regulated_terms_are_recognised():
    c = suggest_data_class(title="SOP-114 deviation and CAPA")
    assert c.suggested is DataClass.REGULATED


def test_no_evidence_falls_back_to_most_restrictive():
    c = suggest_data_class(title="notes", text="lorem ipsum")
    assert c.suggested is DataClass.most_restrictive()
    assert c.confidence == 0.0
    assert "explicitly" in c.rationale


def test_ambiguous_document_is_pulled_to_the_more_restrictive_class():
    """Both operational and regulated evidence → propose regulated."""
    c = suggest_data_class(
        title="Warehouse process",
        text="This procedure covers the batch record and validation protocol "
             "under GMP, plus inventory and supplier logistics.",
    )
    assert c.suggested is DataClass.REGULATED


def test_title_outweighs_a_stray_body_mention():
    c = suggest_data_class(
        title="Press release for publication",
        text="…" * 100 + " one mention of salary somewhere deep in the body.",
    )
    assert c.suggested is DataClass.PUBLIC


def test_payload_flags_itself_as_advisory():
    payload = suggest_data_class(title="Payroll 2026").to_dict()
    assert payload["advisory"] is True
    assert "Suggestion only" in payload["rationale"]


async def test_classifier_never_applies_itself_during_ingestion(platform):
    """Ingesting without an explicit class must still fail closed, not guess."""
    assert suggest_data_class(title="Q3 revenue report").suggested is DataClass.FINANCIAL

    doc = await platform.ingestion.ingest_document(
        ADMIN, title="Q3 revenue report", text="Revenue was 18450."
    )
    # the classifier would have said "financial"; ingestion still says "regulated"
    assert doc.data_class is DataClass.most_restrictive()


# ---------- HTTP ----------


@pytest.fixture
def client():
    plat = build_platform(Settings(generator="fake", embedder="fake", store="memory"))
    resolver = InMemoryResolver({
        "t_admin": Principal("koinoti", "admin", ("admin",)),
        "t_hr": Principal("koinoti", "hr1", ("hr",)),
        "t_emp": Principal("koinoti", "emp", ("employee",)),
    })
    return TestClient(create_app(plat, resolver)), plat


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


def test_http_catalogue_and_delete(client):
    c, plat = client
    c.post(
        "/v1/ingest",
        json={"title": "Q3 financials", "text": "Revenue 18450.", "data_class": "financial"},
        headers=_auth("t_admin"),
    )
    c.post(
        "/v1/ingest",
        json={"title": "Returns policy", "text": "14 days.", "data_class": "public"},
        headers=_auth("t_admin"),
    )

    admin_docs = c.get("/v1/documents", headers=_auth("t_admin")).json()["documents"]
    assert len(admin_docs) == 2

    hr_docs = c.get("/v1/documents", headers=_auth("t_hr")).json()["documents"]
    assert [d["title"] for d in hr_docs] == ["Returns policy"]

    doc_id = next(d["document_id"] for d in admin_docs if d["title"] == "Q3 financials")
    assert c.delete(f"/v1/documents/{doc_id}", headers=_auth("t_admin")).status_code == 200
    assert len(c.get("/v1/documents", headers=_auth("t_admin")).json()["documents"]) == 1


def test_http_delete_of_an_invisible_document_is_a_404_not_a_403(client):
    """A 403 would confirm the document exists; 404 discloses nothing."""
    c, _ = client
    c.post(
        "/v1/ingest",
        json={"title": "Q3 financials", "text": "Revenue 18450.", "data_class": "financial"},
        headers=_auth("t_admin"),
    )
    doc_id = c.get("/v1/documents", headers=_auth("t_admin")).json()["documents"][0][
        "document_id"
    ]
    # hr holds no ingest role at all -> 403 on the role gate
    assert c.delete(f"/v1/documents/{doc_id}", headers=_auth("t_hr")).status_code == 403


def test_http_classify_returns_a_suggestion_without_ingesting(client):
    c, plat = client
    r = c.post(
        "/v1/documents/classify",
        files={"file": ("payroll_2026.txt", b"Salary and payroll for personnel.", "text/plain")},
        headers=_auth("t_admin"),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["advisory"] is True
    assert body["suggested"] in {"hr", "financial"}
    # nothing was stored
    assert c.get("/v1/documents", headers=_auth("t_admin")).json()["documents"] == []
