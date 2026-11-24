"""Turn the dataset into the three shapes the platform can be pointed at.

    python testbench/build.py

writes into ``testbench/build/``:

* ``apteka_pg.sql``     — schema + rows + a read-only login, for Postgres
* ``apteka_mysql.sql``  — the same, in MySQL's dialect
* ``apteka.db``         — a SQLite file, for the "drop a database file" path
* ``schema_notes.md``   — a short human description to upload as a document

The dialects differ in small, real ways (booleans, quoting, how a read-only
user is made), which is exactly what the DB wizard has to cope with — so the
emitters are written out rather than abstracted into one.
"""

from __future__ import annotations

import pathlib
import sqlite3

from dataset import COLUMNS, END, PRODUCTS, START, STORES, build

OUT = pathlib.Path(__file__).parent / "build"
DB_NAME = "apteka"
READER = ("karag_reader", "readonly")

TABLE_ORDER = ("stores", "products", "employees", "sales", "stock")

PG_SCHEMA = """\
DROP TABLE IF EXISTS sales, stock, employees, products, stores CASCADE;

CREATE TABLE stores (
    id        INTEGER PRIMARY KEY,
    name      TEXT NOT NULL,
    city      TEXT NOT NULL,
    address   TEXT,
    opened_on DATE,
    manager   TEXT
);

CREATE TABLE products (
    id                INTEGER PRIMARY KEY,
    name              TEXT NOT NULL,
    category          TEXT NOT NULL,
    form              TEXT,
    unit_price        NUMERIC(10,2) NOT NULL,
    prescription_only BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE employees (
    id             INTEGER PRIMARY KEY,
    store_id       INTEGER NOT NULL REFERENCES stores(id),
    full_name      TEXT NOT NULL,
    role           TEXT NOT NULL,
    hired_on       DATE,
    monthly_salary NUMERIC(10,2)
);

CREATE TABLE sales (
    id         INTEGER PRIMARY KEY,
    store_id   INTEGER NOT NULL REFERENCES stores(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    sold_on    DATE NOT NULL,
    quantity   INTEGER NOT NULL,
    amount     NUMERIC(10,2) NOT NULL
);

CREATE TABLE stock (
    id         INTEGER PRIMARY KEY,
    store_id   INTEGER NOT NULL REFERENCES stores(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    on_hand    INTEGER NOT NULL,
    reorder_at INTEGER NOT NULL,
    counted_on DATE
);

CREATE INDEX sales_sold_on_idx ON sales (sold_on);
CREATE INDEX sales_store_idx ON sales (store_id);

COMMENT ON TABLE sales IS 'Одна строка = одна проданная позиция в чеке';
COMMENT ON COLUMN sales.amount IS 'Сумма строки в сомони, с учётом количества';
COMMENT ON COLUMN employees.monthly_salary IS 'Оклад в сомони — конфиденциально';
COMMENT ON COLUMN stock.reorder_at IS 'Порог, ниже которого позицию нужно дозаказать';
"""

MYSQL_SCHEMA = """\
CREATE DATABASE IF NOT EXISTS apteka CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE apteka;

DROP TABLE IF EXISTS sales, stock, employees, products, stores;

CREATE TABLE stores (
    id        INT PRIMARY KEY,
    name      VARCHAR(120) NOT NULL,
    city      VARCHAR(60) NOT NULL,
    address   VARCHAR(160),
    opened_on DATE,
    manager   VARCHAR(120)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE products (
    id                INT PRIMARY KEY,
    name              VARCHAR(160) NOT NULL,
    category          VARCHAR(60) NOT NULL,
    form              VARCHAR(60),
    unit_price        DECIMAL(10,2) NOT NULL,
    prescription_only TINYINT(1) NOT NULL DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE employees (
    id             INT PRIMARY KEY,
    store_id       INT NOT NULL,
    full_name      VARCHAR(120) NOT NULL,
    role           VARCHAR(60) NOT NULL,
    hired_on       DATE,
    monthly_salary DECIMAL(10,2) COMMENT 'Оклад в сомони — конфиденциально',
    FOREIGN KEY (store_id) REFERENCES stores(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE sales (
    id         INT PRIMARY KEY,
    store_id   INT NOT NULL,
    product_id INT NOT NULL,
    sold_on    DATE NOT NULL,
    quantity   INT NOT NULL,
    amount     DECIMAL(10,2) NOT NULL COMMENT 'Сумма строки в сомони',
    KEY sales_sold_on_idx (sold_on),
    KEY sales_store_idx (store_id),
    FOREIGN KEY (store_id) REFERENCES stores(id),
    FOREIGN KEY (product_id) REFERENCES products(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Одна строка = одна проданная позиция';

CREATE TABLE stock (
    id         INT PRIMARY KEY,
    store_id   INT NOT NULL,
    product_id INT NOT NULL,
    on_hand    INT NOT NULL,
    reorder_at INT NOT NULL,
    counted_on DATE,
    FOREIGN KEY (store_id) REFERENCES stores(id),
    FOREIGN KEY (product_id) REFERENCES products(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

SQLITE_SCHEMA = """\
CREATE TABLE stores (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, city TEXT NOT NULL,
    address TEXT, opened_on TEXT, manager TEXT);
CREATE TABLE products (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL,
    form TEXT, unit_price REAL NOT NULL, prescription_only INTEGER NOT NULL);
CREATE TABLE employees (
    id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id),
    full_name TEXT NOT NULL, role TEXT NOT NULL, hired_on TEXT,
    monthly_salary REAL);
CREATE TABLE sales (
    id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id),
    product_id INTEGER NOT NULL REFERENCES products(id), sold_on TEXT NOT NULL,
    quantity INTEGER NOT NULL, amount REAL NOT NULL);
CREATE TABLE stock (
    id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id),
    product_id INTEGER NOT NULL REFERENCES products(id), on_hand INTEGER NOT NULL,
    reorder_at INTEGER NOT NULL, counted_on TEXT);
CREATE INDEX sales_sold_on_idx ON sales (sold_on);
"""


def _sql_value(v: object, *, bool_as_int: bool) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return ("1" if v else "0") if bool_as_int else ("TRUE" if v else "FALSE")
    if isinstance(v, (int, float)):
        return repr(v)
    text = str(v)
    if bool_as_int:  # MySQL reads a backslash as an escape character; Postgres does not
        text = text.replace("\\", "\\\\")
    return "'" + text.replace("'", "''") + "'"


def _inserts(table: str, rows: list[tuple], *, bool_as_int: bool, chunk: int = 500) -> str:
    cols = ", ".join(COLUMNS[table])
    out = []
    for start in range(0, len(rows), chunk):
        batch = rows[start:start + chunk]
        values = ",\n".join(
            "  (" + ", ".join(_sql_value(v, bool_as_int=bool_as_int) for v in row) + ")"
            for row in batch
        )
        out.append(f"INSERT INTO {table} ({cols}) VALUES\n{values};\n")
    return "\n".join(out)


def write_postgres(tables: dict[str, list[tuple]]) -> pathlib.Path:
    parts = [f"-- KARAG testbench · {DB_NAME} · Postgres\n", PG_SCHEMA]
    for name in TABLE_ORDER:
        parts.append(_inserts(name, tables[name], bool_as_int=False))
    path = OUT / "apteka_pg.sql"
    path.write_text("\n".join(parts), encoding="utf-8")

    # Kept out of the data file: a dump someone uploads should be schema and
    # rows, not role management — and the import path has to swallow neither.
    user, password = READER
    (OUT / "pg_reader.sql").write_text(f"""\
-- A login that can only read: the wizard is meant to be given one.
DO $$ BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{user}') THEN
        CREATE ROLE {user} LOGIN PASSWORD '{password}';
    END IF;
END $$;
GRANT CONNECT ON DATABASE {DB_NAME} TO {user};
GRANT USAGE ON SCHEMA public TO {user};
GRANT SELECT ON ALL TABLES IN SCHEMA public TO {user};
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO {user};
""", encoding="utf-8")
    return path


def write_mysql(tables: dict[str, list[tuple]]) -> pathlib.Path:
    parts = [f"-- KARAG testbench · {DB_NAME} · MySQL\n", MYSQL_SCHEMA]
    parts.append("SET FOREIGN_KEY_CHECKS = 0;\n")
    for name in TABLE_ORDER:
        parts.append(_inserts(name, tables[name], bool_as_int=True))
    parts.append("SET FOREIGN_KEY_CHECKS = 1;\n")
    path = OUT / "apteka_mysql.sql"
    path.write_text("\n".join(parts), encoding="utf-8")

    user, password = READER
    # mysql_native_password: MySQL 8.0's default (caching_sha2) needs the
    # cryptography wheel on the client side, which is not a dependency here.
    (OUT / "mysql_reader.sql").write_text(f"""\
CREATE USER IF NOT EXISTS '{user}'@'%' IDENTIFIED WITH mysql_native_password BY '{password}';
GRANT SELECT ON {DB_NAME}.* TO '{user}'@'%';
FLUSH PRIVILEGES;
""", encoding="utf-8")
    return path


def write_sqlite(tables: dict[str, list[tuple]]) -> pathlib.Path:
    path = OUT / "apteka.db"
    path.unlink(missing_ok=True)
    con = sqlite3.connect(path)
    con.executescript(SQLITE_SCHEMA)
    for name in TABLE_ORDER:
        rows = [tuple(int(v) if isinstance(v, bool) else v for v in row) for row in tables[name]]
        marks = ", ".join("?" * len(COLUMNS[name]))
        con.executemany(f"INSERT INTO {name} VALUES ({marks})", rows)
    con.commit()
    con.close()
    return path


def write_notes(tables: dict[str, list[tuple]]) -> pathlib.Path:
    """A document to upload on the Documents page, so RAG has something to cite."""
    revenue = sum(r[5] for r in tables["sales"])
    by_store: dict[int, float] = {}
    for _, store_id, _, _, _, amount in tables["sales"]:
        by_store[store_id] = by_store.get(store_id, 0.0) + amount
    lines = [
        "# Сеть аптек «Коиноти» — справка по данным",
        "",
        f"Период выгрузки: {START.isoformat()} — {END.isoformat()}.",
        f"Аптек в сети: {len(STORES)}. Позиций в каталоге: {len(PRODUCTS)}.",
        f"Строк продаж: {len(tables['sales'])}. Выручка за период: {revenue:,.2f} сомони.".replace(",", " "),
        "",
        "## Таблицы",
        "",
        "- **stores** — аптеки: город, адрес, дата открытия, заведующий.",
        "- **products** — каталог: категория, форма выпуска, цена за единицу, признак рецептурного отпуска.",
        "- **employees** — сотрудники: должность, дата найма и **оклад** (конфиденциально, доступ только у руководства).",
        "- **sales** — продажи: одна строка = одна позиция в чеке (аптека, товар, дата, количество, сумма).",
        "- **stock** — остатки на складе аптеки и порог дозаказа.",
        "",
        "## Плановые ориентиры на 2026 год",
        "",
        "- План по выручке сети: 1 900 000 сомони.",
        "- Целевая доля рецептурных позиций: не выше 35% выручки.",
        "- Позиция считается дефицитной, если остаток ниже порога дозаказа (`stock.on_hand < stock.reorder_at`).",
        "",
        "## Выручка по аптекам за период",
        "",
        "| Аптека | Город | Выручка, сомони |",
        "| --- | --- | --- |",
    ]
    for store in STORES:
        lines.append(f"| {store[1]} | {store[2]} | {by_store.get(store[0], 0.0):,.2f} |".replace(",", " "))
    lines.append("")
    path = OUT / "schema_notes.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main() -> None:
    OUT.mkdir(exist_ok=True)
    tables = build()
    written = [
        write_postgres(tables), write_mysql(tables),
        write_sqlite(tables), write_notes(tables),
    ]
    counts = ", ".join(f"{name} {len(rows)}" for name, rows in tables.items())
    print(f"rows: {counts}")
    for path in written:
        print(f"  {path.relative_to(pathlib.Path.cwd())}  {path.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main()
