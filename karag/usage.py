"""Usage metering — token accounting per tenant/user, the basis for billing.

Records input/output tokens and request counts, and aggregates per tenant. The
concept's business model (subscription + usage) needs this; it also feeds a
cost/usage dashboard.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field

# per-tenant event history kept for the usage dashboard's activity charts
_EVENT_HISTORY = 1000
# how many recent events the durable store returns for the activity charts
_SQLITE_EVENT_WINDOW = 5000


@dataclass
class UsageTotals:
    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class UsageRecorder:
    def __init__(self) -> None:
        self._by_tenant: dict[str, UsageTotals] = defaultdict(UsageTotals)
        self._by_user: dict[tuple[str, str], UsageTotals] = defaultdict(UsageTotals)
        self._by_model: dict[tuple[str, str], UsageTotals] = defaultdict(UsageTotals)
        self._events_by_tenant: dict[str, deque[dict]] = defaultdict(
            lambda: deque(maxlen=_EVENT_HISTORY)
        )

    def record(
        self, *, tenant_id: str, user_id: str, usage: dict | None, model: str = ""
    ) -> None:
        usage = usage or {}
        inp = int(usage.get("input_tokens", 0) or 0)
        out = int(usage.get("output_tokens", 0) or 0)
        # A fallback request is billed at the model that actually served it.
        served_by = str(usage.get("served_by") or model or "")
        for bucket in (self._by_tenant[tenant_id], self._by_user[(tenant_id, user_id)]):
            bucket.requests += 1
            bucket.input_tokens += inp
            bucket.output_tokens += out
        by_model = self._by_model[(tenant_id, served_by)]
        by_model.requests += 1
        by_model.input_tokens += inp
        by_model.output_tokens += out
        self._events_by_tenant[tenant_id].append(
            {"ts": time.time(), "input_tokens": inp, "output_tokens": out,
             "model": served_by}
        )

    def tenant_events(self, tenant_id: str) -> list[dict]:
        return list(self._events_by_tenant.get(tenant_id, ()))

    def tenant_totals(self, tenant_id: str) -> UsageTotals:
        return self._by_tenant.get(tenant_id, UsageTotals())

    def user_totals(self, tenant_id: str, user_id: str) -> UsageTotals:
        return self._by_user.get((tenant_id, user_id), UsageTotals())

    def tenant_by_model(self, tenant_id: str) -> dict[str, UsageTotals]:
        """Token totals split by the model that served them — the basis of cost.

        Cost is derived at *read* time from these, never stored, so correcting a
        price list reprices history instead of leaving stale money in a column.
        """
        return {
            model: totals
            for (tid, model), totals in self._by_model.items()
            if tid == tenant_id
        }


class SqliteUsageRecorder:
    """Durable usage metering — survives restarts (unlike the in-memory one).

    Every recorded request is one row; totals are aggregated with SUM/COUNT so
    all-time figures are exact, and the activity charts read the most recent
    window of events. Same interface as :class:`UsageRecorder`.
    """

    def __init__(self, path: str = "karag_usage.db") -> None:
        self._path = path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS usage_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    ts REAL NOT NULL,
                    input_tokens INTEGER NOT NULL,
                    output_tokens INTEGER NOT NULL
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_usage_tenant "
                "ON usage_events (tenant_id, ts)"
            )
            # Added after the first release; existing databases are migrated in
            # place so upgrading does not lose metering history.
            columns = {
                r["name"]
                for r in self._conn.execute("PRAGMA table_info(usage_events)")
            }
            if "model" not in columns:
                self._conn.execute(
                    "ALTER TABLE usage_events ADD COLUMN model TEXT NOT NULL DEFAULT ''"
                )

    def record(
        self, *, tenant_id: str, user_id: str, usage: dict | None, model: str = ""
    ) -> None:
        usage = usage or {}
        inp = int(usage.get("input_tokens", 0) or 0)
        out = int(usage.get("output_tokens", 0) or 0)
        served_by = str(usage.get("served_by") or model or "")
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO usage_events (tenant_id, user_id, ts, input_tokens, "
                "output_tokens, model) VALUES (?,?,?,?,?,?)",
                (tenant_id, user_id, time.time(), inp, out, served_by),
            )

    def _totals(self, where: str, params: tuple) -> UsageTotals:
        with self._lock:
            row = self._conn.execute(
                f"SELECT COUNT(*) AS n, COALESCE(SUM(input_tokens),0) AS i, "
                f"COALESCE(SUM(output_tokens),0) AS o FROM usage_events WHERE {where}",
                params,
            ).fetchone()
        return UsageTotals(
            requests=row["n"], input_tokens=row["i"], output_tokens=row["o"]
        )

    def tenant_totals(self, tenant_id: str) -> UsageTotals:
        return self._totals("tenant_id=?", (tenant_id,))

    def user_totals(self, tenant_id: str, user_id: str) -> UsageTotals:
        return self._totals("tenant_id=? AND user_id=?", (tenant_id, user_id))

    def tenant_by_model(self, tenant_id: str) -> dict[str, UsageTotals]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT model, COUNT(*) AS n, COALESCE(SUM(input_tokens),0) AS i,"
                " COALESCE(SUM(output_tokens),0) AS o FROM usage_events"
                " WHERE tenant_id=? GROUP BY model",
                (tenant_id,),
            ).fetchall()
        return {
            r["model"]: UsageTotals(
                requests=r["n"], input_tokens=r["i"], output_tokens=r["o"]
            )
            for r in rows
        }

    def tenant_events(self, tenant_id: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT ts, input_tokens, output_tokens, model FROM ("
                "  SELECT ts, input_tokens, output_tokens, model FROM usage_events "
                "  WHERE tenant_id=? ORDER BY ts DESC LIMIT ?"
                ") ORDER BY ts ASC",
                (tenant_id, _SQLITE_EVENT_WINDOW),
            ).fetchall()
        return [
            {
                "ts": r["ts"],
                "input_tokens": r["input_tokens"],
                "output_tokens": r["output_tokens"],
                "model": r["model"],
            }
            for r in rows
        ]
