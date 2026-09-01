"""Configuration — stdlib only, loaded from environment variables.

No third-party settings library so the core stays dependency-free. Secrets
(API keys, demo tokens) come from the environment, never from code.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _get(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Settings:
    # provider selection
    generator: str = "fake"  # fake | ollama | anthropic | openai
    # optional second generator that answers when the primary errors out
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
    engineer_model: str = "claude-opus-4-8"
    engineer_enabled: bool = True

    # ollama
    ollama_base_url: str = "http://localhost:11434"
    ollama_chat_model: str = "llama3.1"
    ollama_embed_model: str = "nomic-embed-text"
    ollama_embed_dim: int = 768

    # anthropic
    anthropic_model: str = "claude-opus-4-8"
    anthropic_api_key: str | None = None

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
    # roles that may search the web; empty means everyone who can chat
    web_roles: str = ""

    # postgres
    pg_dsn: str = "postgresql://localhost/karag"

    # retrieval
    top_k: int = 5
    max_iterations: int = 4

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
            anthropic_model=_get("KARAG_ANTHROPIC_MODEL", "claude-opus-4-8"),
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY"),
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
            engineer_model=_get("KARAG_ENGINEER_MODEL", "claude-opus-4-8"),
            engineer_enabled=_get("KARAG_ENGINEER_ENABLED", "1") != "0",
            web_search=_get("KARAG_WEB_SEARCH", "none"),
            web_fetch=_get("KARAG_WEB_FETCH", "auto"),
            brave_api_key=os.environ.get("BRAVE_API_KEY"),
            tavily_api_key=os.environ.get("TAVILY_API_KEY"),
            serper_api_key=os.environ.get("SERPER_API_KEY"),
            web_allow_hosts=_get("KARAG_WEB_ALLOW_HOSTS", ""),
            web_deny_hosts=_get("KARAG_WEB_DENY_HOSTS", ""),
            web_roles=_get("KARAG_WEB_ROLES", ""),
            pg_dsn=_get("KARAG_PG_DSN", "postgresql://localhost/karag"),
            top_k=int(_get("KARAG_TOP_K", "5")),
            max_iterations=int(_get("KARAG_MAX_ITERATIONS", "4")),
        )
