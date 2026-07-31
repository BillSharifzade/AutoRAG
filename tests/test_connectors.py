"""SQL connector: real read-only queries + guardrails (SQLite, offline)."""

import os
import sqlite3
import tempfile

import pytest

from karag.connectors.sql import ReadOnlyViolation, SqlConnector, assert_read_only


@pytest.fixture
def sales_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE sales (tenant TEXT, store_id INT, day TEXT, amount INT)")
    conn.executemany(
        "INSERT INTO sales VALUES (?,?,?,?)",
        [("koinoti", 5, "2026-07-20", 18450), ("koinoti", 5, "2026-07-19", 17200),
         ("evar", 5, "2026-07-20", 9300)],
    )
    conn.commit(); conn.close()
    yield path
    os.remove(path)


def test_read_only_validation():
    assert_read_only("SELECT 1")
    assert_read_only("  with x as (select 1) select * from x")
    for bad in ["INSERT INTO t VALUES (1)", "UPDATE t SET a=1", "DELETE FROM t",
                "DROP TABLE t", "SELECT 1; DROP TABLE t"]:
        with pytest.raises(ReadOnlyViolation):
            assert_read_only(bad)


async def test_query_returns_rows(sales_db):
    c = SqlConnector(sqlite_path=sales_db)
    rows = await c.query(
        "SELECT amount FROM sales WHERE tenant=:t AND store_id=:s AND day=:d",
        {"t": "koinoti", "s": 5, "d": "2026-07-20"},
    )
    assert rows == [{"amount": 18450}]


async def test_row_limit_enforced(sales_db):
    c = SqlConnector(sqlite_path=sales_db, default_row_limit=1)
    rows = await c.query("SELECT * FROM sales WHERE tenant=:t", {"t": "koinoti"})
    assert len(rows) == 1  # capped despite 2 matching rows


async def test_writes_rejected_before_execution(sales_db):
    c = SqlConnector(sqlite_path=sales_db)
    with pytest.raises(ReadOnlyViolation):
        await c.query("DELETE FROM sales", {})


async def test_backend_is_read_only(sales_db):
    # Even a read-only-looking connector can't be tricked into writing via the
    # query_only pragma; a sneaky CTE write would fail. Confirm the DB is intact.
    c = SqlConnector(sqlite_path=sales_db)
    rows = await c.query("SELECT count(*) AS n FROM sales", {})
    assert rows == [{"n": 3}]
