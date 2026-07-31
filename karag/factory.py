"""Composition root: build the gateway, store, and services from Settings.

This is the only place that knows about concrete providers. Swapping the free
Ollama backend for Claude Opus 4.8 is a config change here — no application code
changes, because everything above depends on the ``Gateway`` / ``VectorStore``
abstractions.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .assistants import AssistantRegistry, AssistantService, SqliteAssistantRegistry
from .audit import AuditLog, InMemoryAuditLog, SqliteAuditLog
from .config import Settings
from .connectors.registry import (
    ConnectorStore,
    InMemoryConnectorStore,
    SqliteConnectorStore,
)
from .conversations import (
    ConversationStore,
    InMemoryConversationStore,
    SqliteConversationStore,
)
from .errors import ConfigError
from .knowledge.ingest import IngestionService
from .knowledge.rag import RagService
from .knowledge.retrieve import RetrievalService
from .llm.base import Embedder, Gateway, Generator
from .office import OfficeService
from .orchestrator import Orchestrator
from .scheduler import (
    AlertRuleStore,
    AlertService,
    InMemoryAlertRuleStore,
    SqliteAlertRuleStore,
)
from .skills.catalog import SkillCatalog
from .skills.definitions import (
    InMemorySkillDefinitionStore,
    SkillDefinitionStore,
    SqliteSkillDefinitionStore,
)
from .skills.executor import SkillExecutor
from .skills.registry import SkillRegistry
from .tenants import (
    DirectoryService,
    DirectoryStore,
    InMemoryDirectory,
    SqliteDirectory,
)
from .usage import SqliteUsageRecorder, UsageRecorder
from .vectorstore.base import VectorStore


def _build_single_generator(s: Settings, name: str) -> Generator:
    if name == "fake":
        from .llm.fake import FakeGenerator

        return FakeGenerator()
    if name == "ollama":
        from .llm.ollama import OllamaGenerator

        return OllamaGenerator(base_url=s.ollama_base_url, model=s.ollama_chat_model)
    if name == "anthropic":
        from .llm.anthropic_adapter import AnthropicGenerator

        return AnthropicGenerator(model=s.anthropic_model, api_key=s.anthropic_api_key)
    if name == "openai":
        from .llm.openai_gen import OpenAIGenerator

        return OpenAIGenerator(
            model=s.openai_model,
            api_key=s.openai_api_key,
            reasoning_effort=s.openai_reasoning_effort,
        )
    raise ConfigError(f"unknown generator: {name}")


def build_generator(s: Settings) -> Generator:
    primary = _build_single_generator(s, s.generator)
    if s.fallback_generator and s.fallback_generator != s.generator:
        from .llm.fallback import FallbackGenerator

        return FallbackGenerator(primary, _build_single_generator(s, s.fallback_generator))
    return primary


def build_embedder(s: Settings) -> Embedder:
    if s.embedder == "fake":
        from .llm.fake import HashingEmbedder

        return HashingEmbedder(dim=s.embed_dim)
    if s.embedder == "ollama":
        from .llm.ollama import OllamaEmbedder

        return OllamaEmbedder(
            base_url=s.ollama_base_url,
            model=s.ollama_embed_model,
            dim=s.ollama_embed_dim,
        )
    if s.embedder == "openai":
        from .llm.openai_embed import OpenAIEmbedder

        return OpenAIEmbedder(model=s.openai_embed_model, dim=s.embed_dim)
    if s.embedder == "voyage":
        from .llm.voyage_embed import VoyageEmbedder

        return VoyageEmbedder(model=s.voyage_embed_model, dim=s.embed_dim)
    raise ConfigError(f"unknown embedder: {s.embedder}")


def build_usage_recorder(s: Settings) -> UsageRecorder:
    if s.usage_store == "memory":
        return UsageRecorder()
    if s.usage_store == "sqlite":
        return SqliteUsageRecorder(s.usage_db_path)
    raise ConfigError(f"unknown usage_store: {s.usage_store}")


def build_conversation_store(s: Settings) -> ConversationStore:
    if s.chat_store == "memory":
        return InMemoryConversationStore()
    if s.chat_store == "sqlite":
        return SqliteConversationStore(s.chat_db_path)
    raise ConfigError(f"unknown chat_store: {s.chat_store}")


def build_audit_log(s: Settings) -> AuditLog:
    if s.app_store == "memory":
        return InMemoryAuditLog()
    if s.app_store == "sqlite":
        return SqliteAuditLog(s.app_db_path)
    raise ConfigError(f"unknown app_store: {s.app_store}")


def build_assistant_registry(s: Settings) -> AssistantRegistry:
    if s.app_store == "memory":
        return AssistantRegistry()
    if s.app_store == "sqlite":
        return SqliteAssistantRegistry(s.app_db_path)
    raise ConfigError(f"unknown app_store: {s.app_store}")


def build_connector_store(s: Settings) -> ConnectorStore:
    if s.app_store == "memory":
        return InMemoryConnectorStore()
    if s.app_store == "sqlite":
        return SqliteConnectorStore(s.app_db_path)
    raise ConfigError(f"unknown app_store: {s.app_store}")


def build_definition_store(s: Settings) -> SkillDefinitionStore:
    if s.app_store == "memory":
        return InMemorySkillDefinitionStore()
    if s.app_store == "sqlite":
        return SqliteSkillDefinitionStore(s.app_db_path)
    raise ConfigError(f"unknown app_store: {s.app_store}")


def build_alert_store(s: Settings) -> AlertRuleStore:
    if s.app_store == "memory":
        return InMemoryAlertRuleStore()
    if s.app_store == "sqlite":
        return SqliteAlertRuleStore(s.app_db_path)
    raise ConfigError(f"unknown app_store: {s.app_store}")


def build_directory(s: Settings) -> DirectoryStore:
    if s.app_store == "memory":
        return InMemoryDirectory()
    if s.app_store == "sqlite":
        return SqliteDirectory(s.app_db_path)
    raise ConfigError(f"unknown app_store: {s.app_store}")


def build_store(s: Settings) -> VectorStore:
    if s.store == "memory":
        from .vectorstore.memory import InMemoryVectorStore

        return InMemoryVectorStore()
    if s.store == "sqlite":
        from .vectorstore.sqlite import SqliteVectorStore

        return SqliteVectorStore(s.sqlite_path)
    if s.store == "pgvector":
        from .vectorstore.pgvector import PgVectorStore

        return PgVectorStore(s.pg_dsn)
    raise ConfigError(f"unknown store: {s.store}")


@dataclass
class Platform:
    """A fully-wired KARAG instance."""

    settings: Settings
    gateway: Gateway
    store: VectorStore
    registry: SkillRegistry
    ingestion: IngestionService
    retrieval: RetrievalService
    rag: RagService
    orchestrator: Orchestrator
    office: OfficeService
    audit: AuditLog
    usage: UsageRecorder
    assistants: AssistantRegistry
    assistant_service: AssistantService
    conversations: ConversationStore
    catalog: SkillCatalog
    directory: DirectoryStore
    directory_service: DirectoryService
    executor: SkillExecutor
    alerts: AlertRuleStore
    alert_service: AlertService
    # definitions that failed to materialise at boot (missing connector, unset
    # env var). Surfaced by /health so a broken skill is visible, not silent.
    skill_load_errors: list[str] = field(default_factory=list)


def build_platform(
    settings: Settings | None = None,
    *,
    registry: SkillRegistry | None = None,
    audit: AuditLog | None = None,
    usage: UsageRecorder | None = None,
) -> Platform:
    s = settings or Settings.from_env()
    gateway = Gateway(generator=build_generator(s), embedder=build_embedder(s))
    store = build_store(s)
    reg = registry or SkillRegistry()
    audit_log = audit or build_audit_log(s)
    usage_rec = usage or build_usage_recorder(s)

    ingestion = IngestionService(store, gateway.embedder, audit=audit_log)
    retrieval = RetrievalService(store, gateway.embedder, audit=audit_log)
    rag = RagService(retrieval, gateway.generator)
    executor = SkillExecutor(reg, audit=audit_log)
    orchestrator = Orchestrator(
        gateway, retrieval, reg, executor,
        top_k=s.top_k, max_iterations=s.max_iterations,
        audit=audit_log, usage=usage_rec, language=s.default_language,
    )
    assistants = build_assistant_registry(s)
    assistant_service = AssistantService(assistants, orchestrator)
    conversations = build_conversation_store(s)

    # Stored skills become live tools here: definitions authored through the
    # API/UI are materialised at boot, so a restart restores the catalogue
    # instead of losing it (§5 — skills are the product, not a code artefact).
    catalog = SkillCatalog(
        reg, build_definition_store(s), build_connector_store(s), audit=audit_log
    )
    _, load_errors = catalog.load_all()

    directory = build_directory(s)
    alert_store = build_alert_store(s)
    return Platform(
        settings=s,
        gateway=gateway,
        store=store,
        registry=reg,
        ingestion=ingestion,
        retrieval=retrieval,
        rag=rag,
        orchestrator=orchestrator,
        office=OfficeService(),
        audit=audit_log,
        usage=usage_rec,
        assistants=assistants,
        assistant_service=assistant_service,
        conversations=conversations,
        catalog=catalog,
        directory=directory,
        directory_service=DirectoryService(directory),
        executor=executor,
        alerts=alert_store,
        alert_service=AlertService(alert_store, audit=audit_log),
        skill_load_errors=load_errors,
    )
