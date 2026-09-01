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
from .engineer.proposals import (
    InMemoryProposalStore,
    ProposalStore,
    SqliteProposalStore,
)
from .engineer.service import CodeChangeService
from .engineer.skills import engineer_skills
from .engineer.workspace import GitWorkspace
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
from .selfknowledge.codebase import CodebaseIndex
from .selfknowledge.skills import platform_skills
from .skills.admin_skills import admin_skills
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
from .web.base import PageFetcher, WebSearcher
from .web.guard import WebPolicy
from .web.skills import web_skills


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


def build_proposal_store(s: Settings) -> ProposalStore:
    if s.app_store == "memory":
        return InMemoryProposalStore()
    if s.app_store == "sqlite":
        return SqliteProposalStore(s.app_db_path)
    raise ConfigError(f"unknown app_store: {s.app_store}")


def build_engineer_generator(s: Settings) -> Generator | None:
    """The stronger model reserved for turns that may write code.

    Returns ``None`` when self-modification is disabled, or when the primary
    generator is already the engineer model (no point holding two clients), or
    when the configured generator isn't Anthropic — the Opus requirement only
    makes sense on the provider that has it.
    """
    if not s.engineer_enabled or not s.engineer_model:
        return None
    if s.generator != "anthropic" or s.anthropic_model == s.engineer_model:
        return None
    from .llm.anthropic_adapter import AnthropicGenerator

    return AnthropicGenerator(model=s.engineer_model, api_key=s.anthropic_api_key)


def build_web_policy(s: Settings) -> "WebPolicy":
    """Where this deployment may go on the open internet."""
    from .web.guard import WebPolicy

    def hosts(raw: str) -> tuple[str, ...]:
        return tuple(h.strip().lower() for h in raw.split(",") if h.strip())

    return WebPolicy(
        allow_hosts=hosts(s.web_allow_hosts),
        deny_hosts=hosts(s.web_deny_hosts),
    )


def build_web_searcher(s: Settings) -> "WebSearcher | None":
    """The configured search provider, or ``None`` when the web is switched off.

    ``None`` is not a degraded mode: the skills simply are not registered, so
    the model is never offered a tool it cannot use.
    """
    name = (s.web_search or "none").lower()
    if name in ("", "none", "off"):
        return None
    if name == "fake":
        from .web.base import FakeSearcher

        return FakeSearcher()
    if name == "brave":
        from .web.search import BraveSearcher

        return BraveSearcher(s.brave_api_key or "")
    if name == "tavily":
        from .web.search import TavilySearcher

        return TavilySearcher(s.tavily_api_key or "")
    if name == "serper":
        from .web.search import SerperSearcher

        return SerperSearcher(s.serper_api_key or "")
    raise ConfigError(f"unknown web_search provider: {s.web_search}")


def build_page_fetcher(s: Settings) -> "PageFetcher | None":
    """Reading one page, which is useful with or without a search provider.

    ``auto`` follows search, so turning the web on turns both on. Setting it
    explicitly covers the two lopsided cases: reading links the user pastes
    without paying for search, and searching without letting the assistant open
    what it finds.
    """
    mode = (s.web_fetch or "auto").lower()
    searching = (s.web_search or "none").lower() not in ("", "none", "off")
    enabled = searching if mode in ("auto", "") else mode not in ("0", "false", "off")
    if not enabled:
        return None
    if (s.web_search or "").lower() == "fake":
        from .web.base import FakeFetcher

        return FakeFetcher()
    from .web.fetch import HttpPageFetcher

    return HttpPageFetcher(build_web_policy(s))


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
    codebase: CodebaseIndex
    code_changes: CodeChangeService
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
        self_knowledge=s.self_knowledge,
        engineer_generator=build_engineer_generator(s),
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

    # --- self-knowledge and self-modification --------------------------------
    codebase = CodebaseIndex(s.repo_root)
    code_changes = CodeChangeService(
        GitWorkspace(s.repo_root), build_proposal_store(s), audit=audit_log
    )
    if s.self_knowledge:
        for skill in platform_skills(codebase):
            reg.register(skill)
    if s.engineer_enabled:
        for skill in engineer_skills(code_changes):
            reg.register(skill)

    # --- the open internet, if this deployment allows it ---------------------
    web_roles = frozenset(r.strip() for r in s.web_roles.split(",") if r.strip())
    for skill in web_skills(
        build_web_searcher(s), build_page_fetcher(s), required_roles=web_roles
    ):
        reg.register(skill)

    platform = Platform(
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
        codebase=codebase,
        code_changes=code_changes,
        skill_load_errors=load_errors,
    )

    # Operational skills need the assembled platform (they call its services
    # under the caller's own Principal). The registry is shared by reference,
    # so registering here still reaches the orchestrator built above.
    for skill in admin_skills(platform, audit=audit_log):
        reg.register(skill)
    return platform
