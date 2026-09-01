"""Agent skills — procedures in Anthropic's SKILL.md format, stored as data.

The point of the format is *progressive disclosure*: a skill costs its name and
description until it is actually needed, its instructions arrive only when the
model opens it, and a bundled reference file arrives only when the instructions
point at it. These tests pin all three levels, plus the rules the published
format imposes on the metadata and the RBAC KARAG imposes on top.
"""

import pytest

from karag.config import Settings
from karag.domain import DataClass, Principal
from karag.errors import AccessDenied, ValidationError
from karag.factory import build_platform
from karag.request_context import clear_request_context, untrusted_sources
from karag.skills.agent_skill import (
    SkillResource,
    parse_skill_md,
    render_skill_md,
)

CEO = Principal("koinoti", "ceo1", ("ceo",))
AUTHOR = Principal("koinoti", "dev1", ("skill_author",))
EMPLOYEE = Principal("koinoti", "emp1", ("employee",))
HR = Principal("koinoti", "hr1", ("hr",))

INSTRUCTIONS = """# Writing the weekly report

## Steps
1. Pull last week's totals per store.
2. Compare against the same week last year.
3. Flag any store down more than 10%.

Regional breakdowns: see reference/regions.md
"""

REGIONS = "# Regions\n\nNorth: stores 1-4\nSouth: stores 5-9\n"


@pytest.fixture
def platform():
    return build_platform(Settings(generator="fake", embedder="fake", store="memory"))


def _procedure(platform, principal=CEO, **kw):
    params = dict(
        name="writing-weekly-reports",
        description=(
            "Produces the weekly store performance report in the company's "
            "format. Use when asked for the weekly report, a store performance "
            "summary, or a week-on-week comparison."
        ),
        kind="agent",
        instructions=INSTRUCTIONS,
        resources=(SkillResource(path="reference/regions.md", content=REGIONS),),
        required_data_class=DataClass.OPERATIONAL,
    )
    params.update(kw)
    return platform.catalog.create_skill(principal, **params)


# ---------- progressive disclosure ----------


def test_only_name_and_description_are_offered_up_front(platform):
    _procedure(platform)
    skill = platform.registry.resolve(CEO, "writing-weekly-reports")

    spec = skill.to_tool_spec()
    assert spec.description.startswith("Produces the weekly store performance")
    # Level 2 and 3 must not ride along in the tool catalogue.
    blob = f"{spec.name} {spec.description} {spec.input_schema}"
    assert "Pull last week's totals" not in blob
    assert "North: stores 1-4" not in blob


async def test_opening_the_skill_returns_instructions_and_lists_bundled_files(platform):
    _procedure(platform)
    skill = platform.registry.resolve(CEO, "writing-weekly-reports")

    result = await skill.handler(CEO, {})

    assert result.data["instructions"] == INSTRUCTIONS
    assert result.data["bundled_files"] == ["reference/regions.md"]
    # the body is returned, the file's contents are not — that is level 3
    assert REGIONS not in str(result.data)


async def test_a_bundled_file_arrives_only_when_asked_for_by_name(platform):
    _procedure(platform)
    skill = platform.registry.resolve(CEO, "writing-weekly-reports")

    result = await skill.handler(CEO, {"file": "reference/regions.md"})

    assert result.data["content"] == REGIONS
    assert "reference/regions.md" in result.query_shown


async def test_unknown_bundled_file_reports_what_is_available(platform):
    _procedure(platform)
    skill = platform.registry.resolve(CEO, "writing-weekly-reports")

    result = await skill.handler(CEO, {"file": "../../etc/passwd"})

    assert result.data["error"] == "no_such_file"
    assert result.data["bundled_files"] == ["reference/regions.md"]


async def test_reading_a_procedure_marks_the_turn_as_not_karag_authored(platform):
    """Instructions are text a human typed, so a code change may not rest on them."""
    clear_request_context()
    _procedure(platform)
    skill = platform.registry.resolve(CEO, "writing-weekly-reports")

    await skill.handler(CEO, {})

    assert "skill instructions" in untrusted_sources()
    clear_request_context()


# ---------- RBAC still governs a procedure ----------


def test_a_procedure_is_hidden_from_someone_without_the_clearance(platform):
    _procedure(platform, required_data_class=DataClass.FINANCIAL)

    assert platform.registry.resolve(EMPLOYEE, "writing-weekly-reports") is None
    assert not any(
        s.name == "writing-weekly-reports" for s in platform.registry.visible_for(EMPLOYEE)
    )


def test_author_cannot_publish_a_procedure_above_their_own_clearance(platform):
    with pytest.raises(AccessDenied):
        _procedure(platform, principal=HR, required_data_class=DataClass.FINANCIAL)


def test_non_author_cannot_create_a_procedure(platform):
    with pytest.raises(AccessDenied):
        _procedure(platform, principal=EMPLOYEE)


# ---------- the published format's rules ----------


@pytest.mark.parametrize(
    "name",
    [
        "Writing_Weekly_Reports",  # not lowercase-hyphen
        "writing weekly reports",  # spaces
        "claude-reports",  # reserved word
        "anthropic-helper",  # reserved word
        "x" * 65,  # over 64 characters
        "",
    ],
)
def test_bad_procedure_names_are_rejected(platform, name):
    with pytest.raises(ValidationError):
        _procedure(platform, name=name)


def test_a_procedure_without_a_description_is_rejected(platform):
    # The description is the whole of level 1 — without it the skill can never fire.
    with pytest.raises(ValidationError):
        _procedure(platform, description="   ")


def test_an_over_long_description_is_rejected(platform):
    with pytest.raises(ValidationError):
        _procedure(platform, description="a" * 1025)


def test_xml_tags_in_the_description_are_rejected(platform):
    with pytest.raises(ValidationError):
        _procedure(platform, description="Does <thing>things</thing>. Use for things.")


def test_a_procedure_without_instructions_is_rejected(platform):
    with pytest.raises(ValidationError):
        _procedure(platform, instructions="")


@pytest.mark.parametrize(
    "path",
    ["/etc/passwd", "../secrets.md", "reference\\regions.md", ""],
)
def test_unsafe_bundled_paths_are_rejected(platform, path):
    with pytest.raises(ValidationError):
        _procedure(platform, resources=(SkillResource(path=path, content="x"),))


def test_two_bundled_files_may_not_share_a_path(platform):
    with pytest.raises(ValidationError):
        _procedure(
            platform,
            resources=(
                SkillResource(path="a.md", content="1"),
                SkillResource(path="a.md", content="2"),
            ),
        )


# ---------- a procedure needs no data source ----------


def test_a_procedure_needs_no_connector(platform):
    defn = _procedure(platform)
    assert defn.connector_id == ""
    assert platform.registry.resolve(CEO, "writing-weekly-reports") is not None


async def test_test_run_returns_the_instructions_for_review(platform):
    defn = _procedure(platform)

    run = await platform.catalog.test_skill(CEO, defn.id, {})

    assert run.ok
    assert run.data["instructions"] == INSTRUCTIONS


# ---------- SKILL.md interchange ----------


def test_render_round_trips_through_the_parser(platform):
    md = render_skill_md("writing-weekly-reports", "Produces the report. Use weekly.", INSTRUCTIONS)

    assert md.startswith("---\nname: writing-weekly-reports\n")
    name, description, body = parse_skill_md(md)
    assert name == "writing-weekly-reports"
    assert description == "Produces the report. Use weekly."
    assert body.strip() == INSTRUCTIONS.strip()


def test_parser_joins_a_folded_description():
    md = (
        "---\n"
        "name: handling-refunds\n"
        "description: Walks through a refund request end to end.\n"
        "  Use when a customer asks for money back.\n"
        "---\n\n"
        "# Refunds\n"
    )
    _, description, _ = parse_skill_md(md)
    assert description == (
        "Walks through a refund request end to end. "
        "Use when a customer asks for money back."
    )


def test_parser_rejects_text_that_is_not_a_skill_md():
    with pytest.raises(ValidationError):
        parse_skill_md("# Just some notes\n\nno front matter here")


# ---------- editing, sharing, durability ----------


def test_switching_a_lookup_to_a_procedure_drops_its_connector(platform, tmp_path):
    db = tmp_path / "sales.db"
    import sqlite3

    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE sales (tenant TEXT, amount INT)")
    conn.commit()
    conn.close()
    connector = platform.catalog.create_connector(
        CEO, name="replica", kind="sql_sqlite", config={"path": str(db)}
    )
    lookup = platform.catalog.create_skill(
        CEO,
        name="total_sales",
        description="Total sales.",
        kind="sql",
        connector_id=connector.id,
        param_schema={
            "type": "object", "properties": {}, "required": [],
            "additionalProperties": False,
        },
        sql="SELECT amount FROM sales WHERE tenant = :tenant_id",
    )

    updated = platform.catalog.update_skill(
        CEO,
        lookup.id,
        name="totalling-sales",
        kind="agent",
        instructions="Ask finance.",
    )

    assert updated.connector_id == ""
    assert platform.registry.resolve(CEO, "total_sales") is None
    assert platform.registry.resolve(CEO, "totalling-sales") is not None


def test_a_shared_procedure_copies_whole_without_a_connector(platform):
    source = _procedure(platform, shared=True)
    importer = Principal("evar", "admin2", ("admin",))

    copy = platform.catalog.import_from_library(importer, source.id)

    assert copy.tenant_id == "evar"
    assert copy.instructions == INSTRUCTIONS
    assert copy.resources[0].path == "reference/regions.md"
    assert copy.connector_id == ""


def test_procedures_survive_a_restart(tmp_path):
    db = str(tmp_path / "app.db")
    settings = Settings(
        generator="fake", embedder="fake", store="memory",
        app_store="sqlite", app_db_path=db,
    )
    first = build_platform(settings)
    _procedure(first)

    second = build_platform(settings)

    skill = second.registry.resolve(CEO, "writing-weekly-reports")
    assert skill is not None
    assert not second.skill_load_errors
