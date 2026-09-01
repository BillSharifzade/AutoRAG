"""Reaching the open internet — the guard, the skills, and the citations.

The guard tests carry the weight. Web access is the only capability that points
outward, and the URL it points at can be chosen by a model that has just read a
stranger's web page, so "does it refuse" matters more here than anywhere else in
the platform.
"""

import pytest

from karag.config import Settings
from karag.domain import Principal
from karag.factory import build_platform, build_page_fetcher, build_web_searcher
from karag.request_context import (
    clear_request_context,
    next_source_marker,
    reset_source_markers,
    untrusted_sources,
)
from karag.web.base import FakeFetcher, FakeSearcher, FetchedPage, SearchResult
from karag.web.fetch import html_to_text
from karag.web.guard import WebAccessDenied, WebPolicy, check_url, readable_content_type
from karag.web.skills import read_web_page_skill, search_web_skill, web_skills

CEO = Principal("koinoti", "ceo1", ("ceo",))
EMPLOYEE = Principal("koinoti", "emp1", ("employee",))


@pytest.fixture(autouse=True)
def clean_context():
    clear_request_context()
    reset_source_markers()
    yield
    clear_request_context()


# ---------- the guard: what the platform refuses to reach ----------


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/x",
        "gopher://example.com/",
        "javascript:alert(1)",
        "data:text/html,<h1>hi",
    ],
)
def test_only_http_urls_are_reachable(url):
    with pytest.raises(WebAccessDenied):
        check_url(url, WebPolicy())


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/admin",
        "http://127.0.0.1:8000/v1/accounts",
        "http://0.0.0.0/",
        "http://10.0.0.5/internal",
        "http://192.168.1.1/router",
        "http://172.16.4.4/",
        "http://[::1]/",
        # the cloud credential endpoint — the reason link-local is blocked
        "http://169.254.169.254/latest/meta-data/iam/security-credentials/",
    ],
)
def test_addresses_inside_the_perimeter_are_refused(url):
    with pytest.raises(WebAccessDenied):
        check_url(url, WebPolicy())


def test_an_ipv4_address_wrapped_in_ipv6_is_still_that_address():
    with pytest.raises(WebAccessDenied):
        check_url("http://[::ffff:127.0.0.1]/", WebPolicy())


def test_a_name_that_resolves_inside_is_refused(monkeypatch):
    """A public-looking hostname pointing at a private IP is the usual trick."""
    import karag.web.guard as guard

    monkeypatch.setattr(
        guard, "_resolved_addresses",
        lambda host: [__import__("ipaddress").ip_address("10.1.2.3")],
    )
    with pytest.raises(WebAccessDenied, match="private network"):
        check_url("https://totally-normal.example.com/", WebPolicy())


def test_one_private_answer_is_enough_to_refuse(monkeypatch):
    """DNS may return several addresses; a round-robin must not be a coin flip."""
    import ipaddress

    import karag.web.guard as guard

    monkeypatch.setattr(
        guard, "_resolved_addresses",
        lambda host: [
            ipaddress.ip_address("93.184.216.34"),
            ipaddress.ip_address("127.0.0.1"),
        ],
    )
    with pytest.raises(WebAccessDenied):
        check_url("https://example.com/", WebPolicy())


def test_an_unresolvable_host_is_refused(monkeypatch):
    import socket

    import karag.web.guard as guard

    def boom(*a, **k):
        raise socket.gaierror("nope")

    monkeypatch.setattr(guard.socket, "getaddrinfo", boom)
    with pytest.raises(WebAccessDenied, match="resolve"):
        check_url("https://nowhere.invalid/", WebPolicy())


def test_a_public_address_passes(monkeypatch):
    import ipaddress

    import karag.web.guard as guard

    monkeypatch.setattr(
        guard, "_resolved_addresses",
        lambda host: [ipaddress.ip_address("93.184.216.34")],
    )
    assert check_url("https://example.com/x", WebPolicy()) == "https://example.com/x"


def test_the_allow_list_shuts_out_everything_else(monkeypatch):
    import ipaddress

    import karag.web.guard as guard

    monkeypatch.setattr(
        guard, "_resolved_addresses",
        lambda host: [ipaddress.ip_address("93.184.216.34")],
    )
    policy = WebPolicy(allow_hosts=("example.com",))

    assert check_url("https://example.com/a", policy)
    assert check_url("https://docs.example.com/a", policy)  # subdomains count
    with pytest.raises(WebAccessDenied, match="allowed list"):
        check_url("https://elsewhere.com/a", policy)


def test_the_deny_list_wins_over_the_allow_list(monkeypatch):
    import ipaddress

    import karag.web.guard as guard

    monkeypatch.setattr(
        guard, "_resolved_addresses",
        lambda host: [ipaddress.ip_address("93.184.216.34")],
    )
    policy = WebPolicy(allow_hosts=("example.com",), deny_hosts=("secret.example.com",))
    with pytest.raises(WebAccessDenied, match="blocked"):
        check_url("https://secret.example.com/a", policy)


def test_a_lookalike_host_does_not_match_the_allow_list(monkeypatch):
    """``notexample.com`` must not pass an allow-list holding ``example.com``."""
    import ipaddress

    import karag.web.guard as guard

    monkeypatch.setattr(
        guard, "_resolved_addresses",
        lambda host: [ipaddress.ip_address("93.184.216.34")],
    )
    with pytest.raises(WebAccessDenied):
        check_url("https://notexample.com/", WebPolicy(allow_hosts=("example.com",)))


def test_policy_reads_its_host_lists_from_the_environment():
    policy = WebPolicy.from_env(
        {"KARAG_WEB_ALLOW_HOSTS": "a.com, b.com ", "KARAG_WEB_DENY_HOSTS": "c.com"}
    )
    assert policy.allow_hosts == ("a.com", "b.com")
    assert policy.deny_hosts == ("c.com",)


@pytest.mark.parametrize(
    "ctype,ok",
    [
        ("text/html; charset=utf-8", True),
        ("text/plain", True),
        ("application/json", True),
        ("application/pdf", False),
        ("image/png", False),
        ("application/octet-stream", False),
    ],
)
def test_only_readable_types_are_accepted(ctype, ok):
    assert readable_content_type(ctype) is ok


# ---------- html reduction ----------


def test_html_becomes_readable_text():
    title, text = html_to_text(
        "<html><head><title>Rates</title>"
        "<style>.a{color:red}</style><script>steal()</script></head>"
        "<body><h1>Today</h1><p>The rate is 10.9 &amp; rising.</p>"
        "<p>Second line.</p></body></html>"
    )
    assert title == "Rates"
    assert "steal()" not in text
    assert "color:red" not in text
    assert "The rate is 10.9 & rising." in text
    assert "Second line." in text


# ---------- markers ----------


def test_markers_are_numbered_per_turn():
    assert next_source_marker() == "[W1]"
    assert next_source_marker() == "[W2]"
    reset_source_markers()
    assert next_source_marker() == "[W1]"


# ---------- the skills ----------


async def test_search_returns_results_each_carrying_a_citation():
    searcher = FakeSearcher(
        results=[
            SearchResult(title="Rate today", url="https://a.example/1", snippet="10.9"),
            SearchResult(title="Rate history", url="https://b.example/2", snippet="past"),
        ]
    )
    skill = search_web_skill(searcher)

    result = await skill.handler(CEO, {"query": "somoni usd rate"})

    assert searcher.queries == ["somoni usd rate"]
    assert [r["marker"] for r in result.data["results"]] == ["[W1]", "[W2]"]
    assert [c.source_uri for c in result.citations] == [
        "https://a.example/1",
        "https://b.example/2",
    ]
    # the UI tells a web source from a document by this
    assert all(c.document_id == "web" for c in result.citations)
    assert "somoni usd rate" in result.query_shown


async def test_search_marks_the_turn_as_untrusted():
    await search_web_skill(FakeSearcher()).handler(CEO, {"query": "anything"})
    assert "web search results" in untrusted_sources()


async def test_reading_a_page_returns_its_text_with_a_citation():
    fetcher = FakeFetcher(
        pages={
            "https://a.example/1": FetchedPage(
                url="https://a.example/1", title="Rate today", text="The rate is 10.9."
            )
        }
    )
    skill = read_web_page_skill(fetcher)

    result = await skill.handler(CEO, {"url": "https://a.example/1"})

    assert result.data["text"] == "The rate is 10.9."
    assert result.data["marker"] == "[W1]"
    assert result.citations[0].source_uri == "https://a.example/1"
    assert "web page" in untrusted_sources()


async def test_a_refused_url_is_reported_not_raised():
    """The model should say the page was unreachable, not crash the turn."""

    class Refusing:
        async def fetch(self, url):
            raise WebAccessDenied("points inside the private network")

    result = await read_web_page_skill(Refusing()).handler(
        CEO, {"url": "http://169.254.169.254/"}
    )

    assert result.data["error"] == "not_reachable"
    assert result.citations == []


async def test_an_over_long_page_is_cut_and_says_so():
    from karag.web.skills import MAX_PAGE_CHARS

    fetcher = FakeFetcher(
        pages={
            "https://a.example/big": FetchedPage(
                url="https://a.example/big", title="Big", text="x" * (MAX_PAGE_CHARS + 500)
            )
        }
    )
    result = await read_web_page_skill(fetcher).handler(CEO, {"url": "https://a.example/big"})

    assert len(result.data["text"]) == MAX_PAGE_CHARS
    assert result.data["truncated"] is True


async def test_search_result_count_is_capped():
    from karag.web.skills import MAX_RESULTS

    searcher = FakeSearcher(
        results=[
            SearchResult(title=f"r{i}", url=f"https://e.example/{i}") for i in range(50)
        ]
    )
    result = await search_web_skill(searcher).handler(CEO, {"query": "x", "count": 99})
    assert len(result.data["results"]) <= MAX_RESULTS


def test_web_access_can_be_limited_to_certain_roles():
    skill = search_web_skill(FakeSearcher(), required_roles=frozenset({"ceo"}))
    assert skill.visible_to(CEO)
    assert not skill.visible_to(EMPLOYEE)


def test_web_skills_are_absent_when_nothing_is_configured():
    assert web_skills(None, None) == []
    assert [s.name for s in web_skills(FakeSearcher(), None)] == ["search_web"]


# ---------- wiring ----------


def test_the_platform_offers_no_web_tools_by_default():
    platform = build_platform(Settings(generator="fake", embedder="fake", store="memory"))
    names = {s.name for s in platform.registry.visible_for(CEO)}
    assert "search_web" not in names
    assert "read_web_page" not in names


def test_configuring_a_provider_registers_both_tools():
    platform = build_platform(
        Settings(generator="fake", embedder="fake", store="memory", web_search="fake")
    )
    names = {s.name for s in platform.registry.visible_for(CEO)}
    assert {"search_web", "read_web_page"} <= names


def test_page_reading_can_be_switched_off_on_its_own():
    platform = build_platform(
        Settings(
            generator="fake", embedder="fake", store="memory",
            web_search="fake", web_fetch="0",
        )
    )
    names = {s.name for s in platform.registry.visible_for(CEO)}
    assert "search_web" in names
    assert "read_web_page" not in names


def test_page_reading_can_be_turned_on_without_paying_for_search():
    """"Read this link I pasted" is a real need that costs no search quota."""
    platform = build_platform(
        Settings(
            generator="fake", embedder="fake", store="memory",
            web_search="none", web_fetch="1",
        )
    )
    names = {s.name for s in platform.registry.visible_for(CEO)}
    assert "read_web_page" in names
    assert "search_web" not in names


def test_an_unknown_provider_is_a_configuration_error():
    from karag.errors import ConfigError

    with pytest.raises(ConfigError):
        build_web_searcher(Settings(web_search="altavista"))


def test_nothing_reaches_the_web_by_default():
    assert build_web_searcher(Settings()) is None
    assert build_page_fetcher(Settings()) is None


async def test_a_web_source_reaches_the_answers_citations():
    """The point of the whole feature: an internet claim stays checkable.

    Built without self-knowledge or engineering so the deterministic fake has
    only the web tools to choose from.
    """
    platform = build_platform(
        Settings(
            generator="fake", embedder="fake", store="memory",
            web_search="fake", self_knowledge=False, engineer_enabled=False,
        )
    )

    answer = await platform.orchestrator.ask(CEO, "look it up: query=somoni exchange rate")

    assert "search_web" in answer.skills_used
    assert answer.citations, "a web answer with no source is the thing to prevent"
    assert all(c.document_id == "web" for c in answer.citations)
    assert all(c.source_uri and c.source_uri.startswith("http") for c in answer.citations)
    assert answer.citations[0].marker == "[W1]"
    assert any("search_web" in q for q in answer.queries_shown)


async def test_web_citations_do_not_collide_with_document_markers(seeded_web):
    """Documents number [1], [2]…; the web numbers [W1], [W2] — never the same."""
    platform, principal = seeded_web
    answer = await platform.orchestrator.ask(
        principal, "look it up: query=returns policy elsewhere"
    )

    doc_markers = [c.marker for c in answer.citations if c.document_id != "web"]
    web_markers = [c.marker for c in answer.citations if c.document_id == "web"]
    assert web_markers, "expected at least one web source"
    assert not set(doc_markers) & set(web_markers)


@pytest.fixture
async def seeded_web():
    """A platform holding one document *and* the web tools."""
    from karag.domain import DataClass

    platform = build_platform(
        Settings(
            generator="fake", embedder="fake", store="memory",
            web_search="fake", self_knowledge=False, engineer_enabled=False,
        )
    )
    await platform.ingestion.ingest_document(
        CEO,
        title="Returns Policy",
        text="Customers may return unopened goods within 14 days.",
        data_class=DataClass.PUBLIC,
    )
    return platform, CEO


def test_the_web_can_be_restricted_to_roles_by_configuration():
    platform = build_platform(
        Settings(
            generator="fake", embedder="fake", store="memory",
            web_search="fake", web_roles="ceo,admin",
        )
    )
    assert any(s.name == "search_web" for s in platform.registry.visible_for(CEO))
    assert not any(
        s.name == "search_web" for s in platform.registry.visible_for(EMPLOYEE)
    )
