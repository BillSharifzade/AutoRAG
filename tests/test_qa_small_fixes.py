"""Small defects found while testing the deployed server (2026-11-25)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from karag.api.app import create_app
from karag.api.security import InMemoryResolver
from karag.config import Settings
from karag.domain import DataClass, Principal
from karag.factory import build_platform
from karag.knowledge.ingest import title_from_filename

ADMIN = Principal("koinoti", "admin", ("admin",))


def _client():
    plat = build_platform(Settings(generator="fake", embedder="fake", store="memory"))
    return plat, TestClient(create_app(plat, InMemoryResolver({"t_admin": ADMIN})))


def test_uploaded_titles_drop_the_file_extension():
    assert title_from_filename("Положение_об_отпусках.docx") == "Положение об отпусках"
    assert title_from_filename("Q2 report.PDF") == "Q2 report"
    assert title_from_filename("notes.v2") == "notes.v2"  # not a document extension


async def test_reuploading_replaces_a_copy_stored_with_its_extension():
    plat, _ = _client()
    old = await plat.ingestion.ingest_document(
        ADMIN, title="Прайс.xlsx", text="старый прайс", data_class=DataClass.OPERATIONAL
    )
    new = await plat.ingestion.ingest_file(
        ADMIN, filename="Прайс.txt", data="новый прайс".encode(), data_class=DataClass.OPERATIONAL
    )
    assert new.title == "Прайс"
    assert old.id in new.metadata.get("replaced", [])


def test_bad_base64_in_an_attachment_is_refused():
    _, client = _client()
    r = client.post(
        "/v1/ask",
        json={"query": "что тут?", "attachments": [
            {"kind": "file", "filename": "a.txt", "media_type": "text/plain", "data_b64": "!!not base64!!"}
        ]},
        headers={"Authorization": "Bearer t_admin"},
    )
    assert r.status_code == 400 and "base64" in r.json()["detail"]


def test_language_choice_for_a_configuration_token_is_not_a_404():
    _, client = _client()
    r = client.post("/v1/me/language", json={"language": "ru"},
                    headers={"Authorization": "Bearer t_admin"})
    assert r.status_code == 200 and r.json() == {"language": "ru", "stored": False}


async def test_making_a_file_is_not_a_data_answer():
    """The plane badge said "data"/"mixed" for an answer that only made a file
    and cited nothing; it now follows data skills used and passages cited."""
    plat, _ = _client()
    answer = await plat.orchestrator.ask(ADMIN, "сохрани заметку filename=note.txt content=привет")
    assert answer.skills_used and all(
        plat.registry.resolve(ADMIN, n).category == "output" for n in answer.skills_used
    )
    assert answer.plane == "knowledge"
