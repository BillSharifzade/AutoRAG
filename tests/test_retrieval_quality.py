"""Answer-quality machinery: hybrid retrieval, section-aware chunking, the
relevance gate, cited-only sources, the model's own document search, and the
Claude adapter's request shape on current models (thinking blocks replayed,
the prefix kept stable, refusal fallback, workspace header)."""

from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace

import pytest

from karag.config import Settings
from karag.domain import Chunk, DataClass as DC, Principal
from karag.errors import ValidationError
from karag.factory import build_platform
from karag.knowledge.chunking import chunk_document, split_sections
from karag.knowledge.lexical import query_terms, stem_ru, terms
from karag.llm.anthropic_adapter import AnthropicGenerator, _replayable
from karag.llm.base import STREAM_RESET, ChatMessage, LLMResponse, MsgRole, ToolCall, ToolSpec
from karag.llm.fallback import FallbackGenerator, chain
from karag.orchestrator import SEARCH_TOOL, cited_markers
from karag.vectorstore.memory import InMemoryVectorStore
from karag.vectorstore.sqlite import SqliteVectorStore

ADMIN = Principal("koinoti", "adm", ("admin",))
EMP = Principal("koinoti", "emp", ("employee",))


# ------------------------------------------------------------------ lexical

def test_russian_stemming_folds_inflections():
    assert stem_ru("оклада") == stem_ru("окладом") == stem_ru("оклад")
    assert stem_ru("логгеры") == stem_ru("логгеров")
    assert stem_ru("термолабильных") == stem_ru("термолабильные")


def test_codes_survive_tokenisation_whole_and_in_parts():
    t = terms("Товар АМК-875 по бланку 107/у-НП")
    assert "амк-875" in t and "амк" in t and "875" in t and "107/у-нп" in t


def test_tajik_and_english_light_stemming():
    assert "шикоят" in terms("Шикоятҳои муштариён")
    assert query_terms("Passwords are changed") == ["password", "chang"]


# ------------------------------------------------------------------ chunking

def test_sections_carry_their_heading_path():
    text = "# Политика\n\nвступление\n\n## Пароли\n\nдлина 12\n\n### Смена\n\nкаждые 90 дней"
    assert split_sections(text) == [
        ("Политика", "вступление"),
        ("Политика › Пароли", "длина 12"),
        ("Политика › Пароли › Смена", "каждые 90 дней"),
    ]


def test_long_table_repeats_its_header_in_every_piece():
    rows = "\n".join(f"| Должность {i} | {1000 + i} сомони |" for i in range(80))
    text = f"# Оклады\n\n| Должность | Оклад |\n| --- | --- |\n{rows}"
    pieces = chunk_document(text, max_chars=400)
    assert len(pieces) > 3
    for p in pieces:
        assert p.heading == "Оклады"
        assert p.text.startswith("| Должность | Оклад |\n| --- | --- |")


async def test_ingest_stores_heading_and_embeds_with_context():
    seen: list[str] = []

    class Spy:
        dim = 4

        async def embed(self, texts):
            seen.extend(texts)
            return [[1.0, 0, 0, 0] for _ in texts]

    from karag.knowledge.ingest import IngestionService

    store = InMemoryVectorStore()
    svc = IngestionService(store, Spy())
    await svc.ingest_document(
        ADMIN, title="Положение об оплате труда", data_class=DC.PUBLIC,
        text="# Положение об оплате труда\n\n## Оклады\n\nФармацевт — 4 200 сомони.",
    )
    chunk = next(iter(store._chunks.values()))
    assert chunk.heading == "Оклады"  # the title-only first level is dropped
    assert chunk.text == "Фармацевт — 4 200 сомони."
    assert seen[0].startswith("Положение об оплате труда — Оклады")


# --------------------------------------------------------- keyword search

def _c(cid, tenant, klass, text, vec=(1.0, 0, 0, 0), doc=None):
    return Chunk(id=cid, document_id=doc or cid, tenant_id=tenant, data_class=klass,
                 ordinal=0, text=text, title="Справочник", embedding=list(vec))


@pytest.mark.parametrize("make", [InMemoryVectorStore, lambda: SqliteVectorStore(":memory:")])
async def test_keyword_search_keeps_the_security_contract(make):
    store = make()
    await store.upsert([
        _c("code", "t", DC.OPERATIONAL, "АМК-875 Амоксиклав 875/125 мг №14"),
        _c("near", "t", DC.OPERATIONAL, "АМК-500 Амоксиклав 500/125 мг №20"),
        _c("secret", "t", DC.FINANCIAL, "АМК-875 закупочная цена 41,20"),
        _c("other", "evar", DC.OPERATIONAL, "АМК-875 у другого арендатора"),
    ])
    hits = await store.keyword_search(
        tenant_id="t", terms=query_terms("Что за товар АМК-875?"),
        allowed_classes=frozenset({DC.OPERATIONAL}), top_k=5, query_embedding=[1, 0, 0, 0],
    )
    ids = [h.chunk.id for h in hits]
    assert ids[0] == "code"
    assert "secret" not in ids and "other" not in ids
    assert hits[0].dense_score == pytest.approx(1.0)
    assert await store.keyword_search(
        tenant_id="t", terms=["амк-875"], allowed_classes=frozenset(), top_k=5
    ) == []


async def test_sqlite_upgrades_old_databases_in_place(tmp_path):
    """JSON embeddings become float32 blobs and the keyword index is
    backfilled, so a database written by an earlier version keeps working."""
    path = str(tmp_path / "old.db")
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE karag_chunks (id TEXT PRIMARY KEY, document_id TEXT NOT NULL,"
        " tenant_id TEXT NOT NULL, data_class TEXT NOT NULL, ordinal INTEGER NOT NULL,"
        " title TEXT NOT NULL, source_uri TEXT, text TEXT NOT NULL, embedding TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO karag_chunks VALUES ('old','d','t','public',0,'Правила',NULL,"
        " 'Возврат денег на карту в течение 5 рабочих дней', ?)", (json.dumps([0.0, 1.0]),)
    )
    conn.commit()
    conn.close()

    store = SqliteVectorStore(path)
    kinds = sqlite3.connect(path).execute("SELECT typeof(embedding) FROM karag_chunks").fetchall()
    assert kinds == [("blob",)]
    hits = await store.keyword_search(
        tenant_id="t", terms=query_terms("возврат денег"), allowed_classes=frozenset({DC.PUBLIC}),
    )
    assert [h.chunk.id for h in hits] == ["old"]
    dense = await store.search(
        tenant_id="t", query_embedding=[0.0, 1.0], allowed_classes=frozenset({DC.PUBLIC})
    )
    assert dense[0].score == pytest.approx(1.0)


async def test_sqlite_sees_another_process_writes(tmp_path):
    """The per-tenant vector cache notices commits from another connection
    (the scheduler process syncing a source)."""
    path = str(tmp_path / "shared.db")
    api = SqliteVectorStore(path)
    scheduler = SqliteVectorStore(path)
    await api.upsert([_c("a", "t", DC.PUBLIC, "первый", vec=(1, 0, 0, 0))])
    assert len(await api.search(tenant_id="t", query_embedding=[1, 0, 0, 0],
                                allowed_classes=frozenset({DC.PUBLIC}))) == 1
    await scheduler.upsert([_c("b", "t", DC.PUBLIC, "второй", vec=(1, 0, 0, 0))])
    res = await api.search(tenant_id="t", query_embedding=[1, 0, 0, 0],
                           allowed_classes=frozenset({DC.PUBLIC}))
    assert {r.chunk.id for r in res} == {"a", "b"}


# ------------------------------------------------------- hybrid retrieval

def _platform(**kw):
    settings = Settings(generator="fake", embedder="fake", store="memory", embed_dim=64,
                        self_knowledge=False, engineer_enabled=False, **kw)
    return build_platform(settings)


async def test_hybrid_finds_an_exact_code_the_embedder_cannot_see():
    """The hashing test embedder ignores Cyrillic entirely, so only the keyword
    half of hybrid retrieval can find this passage."""
    plat = _platform(relative_floor=0.0)
    await plat.ingestion.ingest_document(
        ADMIN, title="Коды", text="АМК-875 — Амоксиклав 875/125 мг", data_class=DC.PUBLIC)
    await plat.ingestion.ingest_document(
        ADMIN, title="Other", text="unrelated english text about returns", data_class=DC.PUBLIC)
    hits = await plat.retrieval.retrieve(EMP, "АМК-875", top_k=2)
    assert hits[0].chunk.title == "Коды" and hits[0].lexical_score

    dense_only = _platform(retrieval_mode="dense")
    await dense_only.ingestion.ingest_document(
        ADMIN, title="Коды", text="АМК-875 — Амоксиклав 875/125 мг", data_class=DC.PUBLIC)
    hits = await dense_only.retrieval.retrieve(EMP, "АМК-875", top_k=2)
    assert all(h.lexical_score is None for h in hits)


async def test_relative_floor_drops_passages_far_below_the_best():
    plat = _platform(relative_floor=0.8, retrieval_mode="dense")
    await plat.ingestion.ingest_document(
        ADMIN, title="A", text="return policy refund days receipt", data_class=DC.PUBLIC)
    await plat.ingestion.ingest_document(
        ADMIN, title="B", text="cold chain fridge temperature log", data_class=DC.PUBLIC)
    chunks = await plat.orchestrator._retrieve(EMP, "refund policy receipt days", None)
    assert [c.chunk.title for c in chunks] == ["A"]

    loose = _platform(relative_floor=0.0, retrieval_mode="dense")
    await loose.ingestion.ingest_document(
        ADMIN, title="A", text="return policy refund days receipt", data_class=DC.PUBLIC)
    await loose.ingestion.ingest_document(
        ADMIN, title="B", text="cold chain fridge temperature log", data_class=DC.PUBLIC)
    assert len(await loose.orchestrator._retrieve(EMP, "refund policy receipt days", None)) == 2


# -------------------------------------------------------------- citations

def test_cited_markers_understands_the_ways_models_cite():
    assert cited_markers("см. [1], [3, 4] и [W2]; также [5-6].") == {"1", "3", "4", "W2", "5", "6"}
    assert cited_markers("no sources here [note] [x1]") == set()


class Scripted:
    """A generator that plays back a script and records what it was sent."""

    model = "scripted"

    def __init__(self, steps):
        self.steps = list(steps)
        self.calls: list[dict] = []

    async def generate(self, *, system, messages, tools=None, on_delta=None, tool_choice=None):
        self.calls.append({"messages": list(messages), "tools": [t.name for t in tools or []],
                           "tool_choice": tool_choice})
        step = self.steps.pop(0)
        return step(messages) if callable(step) else step


async def test_answer_lists_only_the_sources_it_cites():
    plat = _platform(relative_floor=0.0)
    for title in ("Alpha", "Beta", "Gamma"):
        await plat.ingestion.ingest_document(
            ADMIN, title=title, text=f"{title.lower()} shared policy words", data_class=DC.PUBLIC)
    plat.gateway.generator = Scripted([LLMResponse(text="Per the policy [2].")])
    ans = await plat.orchestrator.ask(EMP, "shared policy words")
    assert len(ans.diagnostics["retrieved"]) == 3
    assert [c.marker for c in ans.citations] == ["[2]"]


async def test_model_can_search_documents_and_cite_what_it_found():
    plat = _platform(relative_floor=0.0, top_k=1)  # one passage up front
    await plat.ingestion.ingest_document(
        ADMIN, title="Policy", text="returns accepted within fourteen days", data_class=DC.PUBLIC)
    await plat.ingestion.ingest_document(
        ADMIN, title="Codes", text="АМК-875 is Amoxiclav 875", data_class=DC.PUBLIC)
    await plat.ingestion.ingest_document(
        ADMIN, title="Salaries", text="АМК-875 bonus table pharmacist", data_class=DC.HR)

    def answer(messages):
        result = messages[-1].content
        assert "АМК-875 is Amoxiclav 875" in result and "bonus" not in result  # RBAC holds
        marker = next(line.split("]")[0] + "]" for line in result.splitlines()
                      if "Amoxiclav" in line)
        return LLMResponse(text=f"It is Amoxiclav {marker}.")

    gen = Scripted([
        LLMResponse(tool_calls=[ToolCall("s1", SEARCH_TOOL, {"query": "АМК-875"})],
                    stop_reason="tool_use"),
        answer,
    ])
    plat.gateway.generator = gen
    ans = await plat.orchestrator.ask(EMP, "returns policy")
    assert gen.calls[0]["tools"][0] == SEARCH_TOOL
    assert [c.title for c in ans.citations] == ["Codes"]
    assert ans.skills_used == []  # searching documents is not a data-plane skill
    assert any(r["via"] == "search" for r in ans.diagnostics["retrieved"])


async def test_search_tool_survives_an_assistant_allow_list_and_hides_when_empty():
    plat = _platform()
    gen = Scripted([LLMResponse(text="nothing")])
    plat.gateway.generator = gen
    await plat.orchestrator.ask(EMP, "anything at all here")
    assert SEARCH_TOOL not in gen.calls[0]["tools"]  # no documents -> no tool

    await plat.ingestion.ingest_document(
        ADMIN, title="P", text="something to find", data_class=DC.PUBLIC)
    gen = Scripted([LLMResponse(text="ok")])
    plat.gateway.generator = gen
    await plat.orchestrator.ask(EMP, "find something", allowed_skill_names=frozenset())
    assert gen.calls[0]["tools"] == [SEARCH_TOOL]  # documents-only assistant keeps it


async def test_streamed_text_is_reset_when_a_provider_fails_mid_answer():
    class Broken:
        model = "primary"

        async def generate(self, *, system, messages, tools=None, on_delta=None, **kw):
            await on_delta("half an ans")
            raise RuntimeError("connection dropped")

    class Healthy:
        model = "backup"

        async def generate(self, *, system, messages, tools=None, on_delta=None, **kw):
            await on_delta("Full answer.")
            return LLMResponse(text="Full answer.")

    plat = _platform()
    plat.gateway.generator = FallbackGenerator(Broken(), Healthy())
    events: list[dict] = []

    async def on_event(e):
        events.append(e)

    ans = await plat.orchestrator.ask(EMP, "question", on_event=on_event)
    kinds = [e["type"] for e in events if e["type"] in ("delta", "reset")]
    assert kinds == ["delta", "reset", "delta"]
    assert ans.text == "Full answer."
    assert ans.diagnostics["usage"]["served_by"] == "backup"


def test_chain_nests_fallbacks_in_order():
    a, b, c = (SimpleNamespace(model=m) for m in "abc")
    g = chain([a, b, c])
    assert g.primary is a and g.fallback.primary is b and g.fallback.fallback is c


def test_factory_builds_a_comma_separated_fallback_chain():
    from karag.factory import build_generator

    g = build_generator(Settings(generator="fake", fallback_generator="ollama,fake,ollama"))
    assert g.model == "fake-deterministic (fallback: llama3.1)"


# ----------------------------------------------------- Claude request shape

def test_claude_request_keeps_the_prefix_stable_and_opts_into_safeguards():
    gen = AnthropicGenerator(model="claude-opus-5-5", effort="medium", workspace_id="wrkspc_x")
    tools = [ToolSpec("a", "first", {"type": "object"}), ToolSpec("b", "second", {"type": "object"})]
    req = gen._request("sys", [ChatMessage(MsgRole.USER, "q")], tools)
    closing = gen._request("sys", [ChatMessage(MsgRole.USER, "q")], tools, tool_choice="none")
    # the closing "answer now" call keeps the same tools; only tool_choice differs
    assert closing["tools"] == req["tools"] and closing["tool_choice"] == {"type": "none"}
    assert "tool_choice" not in req
    assert req["thinking"]["type"] == "adaptive"
    assert req["thinking"]["block_binding"] == {"prefix_mismatch_behavior": "drop_block"}
    assert req["fallbacks"] == "default"
    assert set(req["betas"]) == {"server-side-fallback-2026-07-01", "thinking-binding-controls-2026-08-01"}
    assert req["output_config"] == {"effort": "medium"}
    assert all(t["eager_input_streaming"] for t in req["tools"])
    assert req["tools"][-1]["cache_control"] == {"type": "ephemeral"}
    assert "temperature" not in req


def test_older_models_get_the_plain_request_shape():
    req = AnthropicGenerator(model="claude-haiku-4-5")._request("s", [], None)
    assert "fallbacks" not in req and "betas" not in req and "output_config" not in req


def test_tool_loop_turns_replay_their_original_blocks_thinking_included():
    thinking = {"type": "thinking", "thinking": "", "signature": "sig"}
    tool_use = {"type": "tool_use", "id": "t1", "name": "a", "input": {}}
    msgs = [
        ChatMessage(MsgRole.USER, "q"),
        ChatMessage(MsgRole.ASSISTANT, "", tool_calls=[ToolCall("t1", "a", {})],
                    provider_blocks=[thinking, tool_use], provider="anthropic"),
        ChatMessage(MsgRole.TOOL, "{}", tool_call_id="t1", name="a"),
    ]
    out = AnthropicGenerator._to_anthropic_messages(msgs)
    assert out[1] == {"role": "assistant", "content": [thinking, tool_use]}
    stripped = AnthropicGenerator._to_anthropic_messages(msgs, keep_thinking=False)
    assert stripped[1]["content"] == [tool_use]
    # blocks recorded by another provider are not replayed to Claude
    msgs[1].provider = "openai"
    assert AnthropicGenerator._to_anthropic_messages(msgs)[1]["content"][0]["type"] == "tool_use"


def test_after_a_mid_output_fallback_only_safe_blocks_before_it_are_echoed():
    content = [
        {"type": "thinking", "signature": "x"}, {"type": "text", "text": "partial"},
        {"type": "tool_use", "id": "half"}, {"type": "fallback"},
        {"type": "thinking", "signature": "y"}, {"type": "text", "text": "rest"},
    ]
    kept = [b["type"] for b in _replayable(content)]
    assert kept == ["text", "fallback", "thinking", "text"]


def test_server_side_fallback_is_billed_to_the_model_that_answered():
    resp = SimpleNamespace(
        model="claude-opus-4-8", stop_reason="end_turn", content=[],
        usage=SimpleNamespace(input_tokens=10, output_tokens=5,
                              cache_read_input_tokens=0, cache_creation_input_tokens=0),
    )
    parsed = AnthropicGenerator._parse(resp, requested_model="claude-opus-5-5")
    assert parsed.usage["served_by"] == "claude-opus-4-8"


# -------------------------------------------------------------- scanned PDF

def _blank_pdf() -> bytes:
    from pypdf import PdfWriter
    import io

    w = PdfWriter()
    w.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


async def test_scanned_pdf_is_read_by_ocr_or_refused_with_a_reason():
    pytest.importorskip("pypdf")
    from karag.knowledge.ingest import IngestionService

    store = InMemoryVectorStore()
    plain = IngestionService(store, _platform().gateway.embedder)
    with pytest.raises(ValidationError, match="no text layer"):
        await plain.ingest_file(ADMIN, filename="scan.pdf", data=_blank_pdf(),
                                data_class=DC.PUBLIC)

    async def ocr(data: bytes) -> str:
        return "# Акт\n\nПрепараты помещены в карантин."

    reading = IngestionService(store, _platform().gateway.embedder, ocr=ocr)
    doc = await reading.ingest_file(ADMIN, filename="scan.pdf", data=_blank_pdf(),
                                    data_class=DC.PUBLIC)
    assert doc.metadata["ocr"] is True
    assert await store.count(tenant_id="koinoti") == 1


# ------------------------------------------------------------------- prices

def test_cache_reads_are_priced_per_model():
    from karag.usage import billable_input_tokens

    usage = {"input_tokens": 100, "cache_read_input_tokens": 1000}
    assert billable_input_tokens(usage, "claude-opus-5-5") == 150   # 0.05x
    assert billable_input_tokens(usage, "claude-sonnet-5") == 200   # 0.1x
