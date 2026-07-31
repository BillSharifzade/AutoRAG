"""Durable usage metering — SQLite recorder survives a fresh instance."""

from karag.usage import SqliteUsageRecorder, UsageRecorder


def _record_a_few(rec):
    rec.record(tenant_id="koinoti", user_id="u1", usage={"input_tokens": 100, "output_tokens": 20})
    rec.record(tenant_id="koinoti", user_id="u2", usage={"input_tokens": 50, "output_tokens": 5})
    rec.record(tenant_id="other", user_id="x", usage={"input_tokens": 999, "output_tokens": 999})


def test_memory_and_sqlite_agree(tmp_path):
    mem = UsageRecorder()
    sql = SqliteUsageRecorder(str(tmp_path / "u.db"))
    for rec in (mem, sql):
        _record_a_few(rec)
        t = rec.tenant_totals("koinoti")
        assert (t.requests, t.input_tokens, t.output_tokens, t.total_tokens) == (2, 150, 25, 175)
        assert rec.user_totals("koinoti", "u1").input_tokens == 100
        # tenant isolation
        assert rec.tenant_totals("other").requests == 1
        evs = rec.tenant_events("koinoti")
        assert len(evs) == 2 and evs[0]["ts"] <= evs[1]["ts"]


def test_sqlite_persists_across_instances(tmp_path):
    path = str(tmp_path / "u.db")
    first = SqliteUsageRecorder(path)
    _record_a_few(first)
    # a brand-new recorder on the same file sees the earlier data (durability)
    second = SqliteUsageRecorder(path)
    t = second.tenant_totals("koinoti")
    assert t.requests == 2 and t.total_tokens == 175
    assert len(second.tenant_events("koinoti")) == 2
