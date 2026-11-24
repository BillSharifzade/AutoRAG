"""A stand-in for a customer's public API, for testing the Data wizard.

Stdlib only, no auth, GET only — the shape KARAG's guided integration expects.
It serves the same pharmacy data as the test databases in the four payload
shapes the profiler has to recognise:

    GET /v1/products            a bare JSON array of records
    GET /v1/sales/daily         records buried in an envelope (data.items)
    GET /v1/stores.csv          text/csv
    GET /v1/rate                a single JSON object, no list at all
    GET /v1/inventory           records + query parameters (?store=&low=&limit=)
    GET /v1/slow                answers after ~3 s, for the "is it hanging" case
    GET /v1/broken              500, to see how a failed source is reported
    anything else               404

Run it directly (``python testbench/api_server.py``) or, as ``up.sh`` does, in
a container on the platform's network so the API server can reach it by name.
"""

from __future__ import annotations

import csv
import io
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from dataset import COLUMNS, END, START, as_dicts, build

TABLES = build()
PRODUCTS = as_dicts("products", TABLES["products"])
STORES = as_dicts("stores", TABLES["stores"])
STOCK = as_dicts("stock", TABLES["stock"])
SALES = as_dicts("sales", TABLES["sales"])

STORE_NAME = {s["id"]: s["name"] for s in STORES}
PRODUCT_NAME = {p["id"]: p["name"] for p in PRODUCTS}

# Pre-aggregated: one record per store per day, which is what a reporting API
# would actually expose (and small enough to be a sane document).
DAILY: list[dict] = []
_acc: dict[tuple[str, int], dict] = {}
for _s in SALES:
    key = (_s["sold_on"], _s["store_id"])
    row = _acc.setdefault(key, {
        "date": _s["sold_on"],
        "store_id": _s["store_id"],
        "store": STORE_NAME[_s["store_id"]],
        "receipts": 0,
        "items": 0,
        "revenue": 0.0,
    })
    row["receipts"] += 1
    row["items"] += _s["quantity"]
    row["revenue"] = round(row["revenue"] + _s["amount"], 2)
DAILY = sorted(_acc.values(), key=lambda r: (r["date"], r["store_id"]))

INVENTORY = [
    {
        "store": STORE_NAME[r["store_id"]],
        "product": PRODUCT_NAME[r["product_id"]],
        "on_hand": r["on_hand"],
        "reorder_at": r["reorder_at"],
        "shortage": r["on_hand"] < r["reorder_at"],
        "counted_on": r["counted_on"],
    }
    for r in STOCK
]


def _csv_bytes(rows: list[dict], columns: tuple[str, ...]) -> bytes:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(columns), extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    server_version = "KaragTestbench/1.0"

    def do_GET(self) -> None:  # noqa: N802 — stdlib's spelling
        parts = urlsplit(self.path)
        query = parse_qs(parts.query)
        route = parts.path.rstrip("/") or "/"

        if route in ("/", "/v1"):
            return self._json({
                "service": "Koinoti Apteka · demo API",
                "endpoints": ["/v1/products", "/v1/sales/daily", "/v1/stores.csv",
                              "/v1/rate", "/v1/inventory", "/v1/slow", "/v1/broken"],
                "period": {"from": START.isoformat(), "to": END.isoformat()},
            })

        if route == "/v1/products":
            category = (query.get("category") or [""])[0]
            rows = [p for p in PRODUCTS if not category or p["category"] == category]
            return self._json(rows)

        if route == "/v1/sales/daily":
            rows = DAILY
            if (store := (query.get("store") or [""])[0]):
                rows = [r for r in rows if str(r["store_id"]) == store]
            if (since := (query.get("since") or [""])[0]):
                rows = [r for r in rows if r["date"] >= since]
            limit = int((query.get("limit") or ["400"])[0])
            rows = rows[-limit:]
            # the envelope is the point: the profiler has to find data.items
            return self._json({
                "status": "ok",
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "currency": "TJS",
                "data": {"total": len(rows), "items": rows},
            })

        if route in ("/v1/stores.csv", "/v1/stores"):
            body = _csv_bytes(STORES, COLUMNS["stores"])
            return self._send(200, "text/csv; charset=utf-8", body)

        if route == "/v1/rate":
            return self._json({
                "base": "TJS", "date": END.isoformat(),
                "rates": {"USD": 10.92, "EUR": 11.84, "RUB": 0.118},
                "source": "Национальный банк Таджикистана (демо)",
            })

        if route == "/v1/inventory":
            rows = INVENTORY
            if (store := (query.get("store") or [""])[0]):
                rows = [r for r in rows if store.lower() in r["store"].lower()]
            if (query.get("low") or [""])[0] in ("1", "true", "yes"):
                rows = [r for r in rows if r["shortage"]]
            limit = int((query.get("limit") or ["200"])[0])
            return self._json(rows[:limit])

        if route == "/v1/slow":
            time.sleep(3)
            return self._json({"status": "ok", "waited_s": 3})

        if route == "/v1/broken":
            return self._send(500, "application/json",
                              b'{"error":"upstream inventory service unavailable"}')

        return self._send(404, "application/json",
                          b'{"error":"no such endpoint"}')

    # POST exists only to prove the flow is read-only by construction.
    def do_POST(self) -> None:  # noqa: N802
        self._send(405, "application/json", b'{"error":"this API is read-only"}')

    def _json(self, payload: object) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=1).encode("utf-8")
        self._send(200, "application/json; charset=utf-8", body)

    def _send(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:
        print(f"{self.address_string()} {fmt % args}", flush=True)


def main() -> None:
    port = int(os.environ.get("PORT", "8100"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"testbench API on :{port} — {len(PRODUCTS)} products, "
          f"{len(DAILY)} daily rows, {len(INVENTORY)} stock rows", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
