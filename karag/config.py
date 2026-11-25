"""Configuration — stdlib only, loaded from environment variables.

No third-party settings library so the core stays dependency-free. Secrets
(API keys, demo tokens) come from the environment, never from code.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _get(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _float_or_none(raw: str | None) -> float | None:
    raw = (raw or "").strip()
    return float(raw) if raw else None


@dataclass(frozen=True)
class Settings:
    # provider selection
    generator: str = "fake"  # fake | ollama | anthropic | openai
    # generators that answer, in order, when the one before them errors out
    # (comma-separated: "openai" or "anthropic_backup,openai")
    fallback_generator: str | None = None
    embedder: str = "fake"  # fake | ollama | openai | voyage
    store: str = "memory"  # memory | sqlite | pgvector

    # embeddings
    embed_dim: int = 256

    # openai / voyage embedders
    openai_embed_model: str = "text-embedding-3-large"
    voyage_embed_model: str = "voyage-3"

    # openai generator
    openai_model: str = "gpt-5.5"
    openai_api_key: str | None = None
    # set to "none" to run a gpt-5.6 reasoning model with tools on chat/completions
    openai_reasoning_effort: str | None = None

    # sqlite store
    sqlite_path: str = ":memory:"

    # chat history persistence
    chat_store: str = "memory"  # memory | sqlite
    chat_db_path: str = "karag_chats.db"

    # usage metering persistence
    usage_store: str = "memory"  # memory | sqlite
    usage_db_path: str = "karag_usage.db"

    # application database: tenants, accounts, connectors, skill definitions,
    # assistants, alert rules and the audit trail (§12's "app database" row).
    app_store: str = "memory"  # memory | sqlite
    app_db_path: str = "karag_app.db"

    # answer language: auto (mirror the user) | ru | tg | en
    default_language: str = "auto"

    # platform self-knowledge: hand the assistant its own handbook + role guide,
    # and let it read its own source to answer implementation questions.
    self_knowledge: bool = True
    repo_root: str = "."

    # code changes run on a stronger model than ordinary chat; empty disables
    # the self-modification capability entirely.
    engineer_model: str = "claude-opus-5-5"
    engineer_enabled: bool = True

    # ollama
    ollama_base_url: str = "http://localhost:11434"
    ollama_chat_model: str = "llama3.1"
    ollama_embed_model: str = "nomic-embed-text"
    ollama_embed_dim: int = 768

    # anthropic — Sonnet 5.5 at medium effort is the measured choice for the
    # RAG agent: on evals/ it matched Opus 5.5 answer for answer at about a
    # third of the cost (see evals/README.md); Opus 5.5 is kept for engineer
    # turns, Haiku 5.5 for reading scanned PDFs.
    anthropic_model: str = "claude-sonnet-5-5"
    anthropic_api_key: str | None = None
    # an organisation-scoped key must name the workspace on every request
    anthropic_workspace_id: str | None = None
    # how much the model thinks: low | medium | high | xhigh | max
    anthropic_effort: str = "medium"
    # thinking counts toward this, so it is sized for thinking + the reply
    anthropic_max_tokens: int = 32000
    # server-side refusal fallback: "default" lets the API pick the model for
    # the refusal category; "" turns it off
    anthropic_refusal_fallback: str = "default"
    # a second Anthropic account/key used only as a fallback link in the chain
    # (name it "anthropic_backup" in KARAG_FALLBACK_GENERATOR)
    backup_anthropic_api_key: str | None = None
    backup_anthropic_model: str = "claude-sonnet-5-5"
    backup_anthropic_workspace_id: str | None = None

    # scanned PDFs: read the page images with Claude when the text layer is
    # empty. auto = on whenever an Anthropic key is configured; off = refuse
    # the upload with a clear message instead.
    pdf_ocr: str = "auto"
    ocr_model: str = "claude-haiku-5-5"

    # web access: the one capability that points outward, so it is off unless
    # asked for. "none" disables search; page reading follows it unless
    # web_fetch is set independently.
    web_search: str = "none"  # none | brave | tavily | serper | fake
    # auto: page reading follows search. "1" turns it on by itself, which is
    # the useful configuration for "read this link I pasted" without paying a
    # search provider; "0" allows search but no page reading.
    web_fetch: str = "auto"  # auto | 1 | 0
    brave_api_key: str | None = None
    tavily_api_key: str | None = None
    serper_api_key: str | None = None
    # comma-separated; empty allow-list means "anywhere public"
    web_allow_hosts: str = ""
    web_deny_hosts: str = ""
    # internal hosts cleared by name (an intranet API, a test double); only
    # these are exempt from the "must resolve to a public address" rule
    web_allow_private_hosts: str = ""
    # roles that may search the web; empty means everyone who can chat
    web_roles: str = ""

    # postgres
    pg_dsn: str = "postgresql://localhost/karag"

    # retrieval
    top_k: int = 5
    # tool-calling rounds per turn; a free database query often needs an
    # exploratory SELECT or two before the real one
    max_iterations: int = 8
    # chunks scoring below this cosine similarity are not shown to the model;
    # 0 keeps everything non-negative, ~0.2 is a sane floor for real embedders
    min_score: float = 0.0
    # at most this many chunks of one document per answer, so a long document
    # cannot crowd every other source out of the context
    max_per_document: int = 2
    # a skill that has not answered by then is reported as failed
    skill_timeout_s: float = 60.0
    # hybrid = embeddings + keyword (BM25) fused; dense = embeddings only
    retrieval_mode: str = "hybrid"
    # chunk by section and embed each passage together with its document
    # title and heading (off = the plain sliding-window chunks of old)
    contextual_chunks: bool = True
    # a passage is shown only if its similarity is at least this fraction of
    # the best passage's (or it matched the question's words); 0 disables
    relative_floor: float = 0.8
    # offer the model a search_documents tool so it can look again with
    # better words instead of relying on the first search alone
    agentic_search: bool = True

    # cost control: a tenant's monthly model spend cap in USD (an account
    # setting overrides it; empty = no cap), and per-user requests per minute
    tenant_monthly_budget_usd: float | None = None
    rate_limit_per_minute: int = 30

    # where uploaded database files (SQLite, imported SQL dumps) are kept
    upload_dir: str = "./data/uploads"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            generator=_get("KARAG_GENERATOR", "fake"),
            fallback_generator=os.environ.get("KARAG_FALLBACK_GENERATOR"),
            embedder=_get("KARAG_EMBEDDER", "fake"),
            store=_get("KARAG_STORE", "memory"),
            embed_dim=int(_get("KARAG_EMBED_DIM", "256")),
            ollama_base_url=_get("KARAG_OLLAMA_URL", "http://localhost:11434"),
            ollama_chat_model=_get("KARAG_OLLAMA_CHAT_MODEL", "llama3.1"),
            ollama_embed_model=_get("KARAG_OLLAMA_EMBED_MODEL", "nomic-embed-text"),
            ollama_embed_dim=int(_get("KARAG_OLLAMA_EMBED_DIM", "768")),
            anthropic_model=_get("KARAG_ANTHROPIC_MODEL", "claude-sonnet-5-5"),
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY"),
            anthropic_workspace_id=os.environ.get("KARAG_ANTHROPIC_WORKSPACE_ID") or None,
            anthropic_effort=_get("KARAG_ANTHROPIC_EFFORT", "medium"),
            anthropic_max_tokens=int(_get("KARAG_ANTHROPIC_MAX_TOKENS", "32000")),
            anthropic_refusal_fallback=_get("KARAG_ANTHROPIC_REFUSAL_FALLBACK", "default"),
            backup_anthropic_api_key=os.environ.get("KARAG_BACKUP_ANTHROPIC_API_KEY") or None,
            backup_anthropic_model=_get("KARAG_BACKUP_ANTHROPIC_MODEL", "claude-sonnet-5-5"),
            backup_anthropic_workspace_id=os.environ.get("KARAG_BACKUP_ANTHROPIC_WORKSPACE_ID") or None,
            pdf_ocr=_get("KARAG_PDF_OCR", "auto"),
            ocr_model=_get("KARAG_OCR_MODEL", "claude-haiku-5-5"),
            openai_embed_model=_get("KARAG_OPENAI_EMBED_MODEL", "text-embedding-3-large"),
            openai_model=_get("KARAG_OPENAI_MODEL", "gpt-5.5"),
            openai_api_key=os.environ.get("OPENAI_API_KEY"),
            openai_reasoning_effort=os.environ.get("KARAG_OPENAI_REASONING_EFFORT"),
            voyage_embed_model=_get("KARAG_VOYAGE_EMBED_MODEL", "voyage-3"),
            sqlite_path=_get("KARAG_SQLITE_PATH", ":memory:"),
            chat_store=_get("KARAG_CHAT_STORE", "memory"),
            chat_db_path=_get("KARAG_CHAT_DB", "karag_chats.db"),
            usage_store=_get("KARAG_USAGE_STORE", "memory"),
            usage_db_path=_get("KARAG_USAGE_DB", "karag_usage.db"),
            app_store=_get("KARAG_APP_STORE", "memory"),
            app_db_path=_get("KARAG_APP_DB", "karag_app.db"),
            default_language=_get("KARAG_LANGUAGE", "auto"),
            self_knowledge=_get("KARAG_SELF_KNOWLEDGE", "1") != "0",
            repo_root=_get("KARAG_REPO_ROOT", "."),
            engineer_model=_get("KARAG_ENGINEER_MODEL", "claude-opus-5-5"),
            engineer_enabled=_get("KARAG_ENGINEER_ENABLED", "1") != "0",
            web_search=_get("KARAG_WEB_SEARCH", "none"),
            web_fetch=_get("KARAG_WEB_FETCH", "auto"),
            brave_api_key=os.environ.get("BRAVE_API_KEY"),
            tavily_api_key=os.environ.get("TAVILY_API_KEY"),
            serper_api_key=os.environ.get("SERPER_API_KEY"),
            web_allow_hosts=_get("KARAG_WEB_ALLOW_HOSTS", ""),
            web_deny_hosts=_get("KARAG_WEB_DENY_HOSTS", ""),
            web_allow_private_hosts=_get("KARAG_WEB_ALLOW_PRIVATE_HOSTS", ""),
            web_roles=_get("KARAG_WEB_ROLES", ""),
            pg_dsn=_get("KARAG_PG_DSN", "postgresql://localhost/karag"),
            top_k=int(_get("KARAG_TOP_K", "5")),
            max_iterations=int(_get("KARAG_MAX_ITERATIONS", "8")),
            min_score=float(_get("KARAG_MIN_SCORE", "0")),
            max_per_document=int(_get("KARAG_MAX_PER_DOCUMENT", "2")),
            skill_timeout_s=float(_get("KARAG_SKILL_TIMEOUT", "60")),
            retrieval_mode=_get("KARAG_RETRIEVAL_MODE", "hybrid"),
            contextual_chunks=_get("KARAG_CONTEXTUAL_CHUNKS", "1") != "0",
            relative_floor=float(_get("KARAG_RELATIVE_FLOOR", "0.8")),
            agentic_search=_get("KARAG_AGENTIC_SEARCH", "1") != "0",
            tenant_monthly_budget_usd=_float_or_none(os.environ.get("KARAG_TENANT_MONTHLY_BUDGET_USD")),
            rate_limit_per_minute=int(_get("KARAG_RATE_LIMIT_PER_MINUTE", "30")),
            upload_dir=_get("KARAG_UPLOAD_DIR", "./data/uploads"),
        )
