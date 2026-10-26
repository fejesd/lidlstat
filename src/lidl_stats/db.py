"""SQLite storage: raw API responses plus the parsed items derived from them."""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from lidl_stats.parser import parse_number, parse_receipt

SCHEMA = """
CREATE TABLE IF NOT EXISTS receipts (
    id            TEXT PRIMARY KEY,
    date          TEXT NOT NULL,  -- local time, 'YYYY-MM-DDTHH:MM:SS'
    store_code    TEXT NOT NULL DEFAULT '',
    store_name    TEXT NOT NULL DEFAULT '',
    total         REAL NOT NULL,
    currency      TEXT NOT NULL DEFAULT '',
    items_total   REAL NOT NULL DEFAULT 0,
    discount      REAL NOT NULL DEFAULT 0,
    parse_source  TEXT NOT NULL DEFAULT 'none',
    raw_summary   TEXT NOT NULL,
    raw_detail    TEXT NOT NULL,
    fetched_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS receipts_date ON receipts(date);

CREATE TABLE IF NOT EXISTS items (
    receipt_id  TEXT NOT NULL REFERENCES receipts(id) ON DELETE CASCADE,
    line_no     INTEGER NOT NULL,
    name        TEXT NOT NULL,
    code        TEXT NOT NULL DEFAULT '',
    quantity    REAL NOT NULL,
    unit_price  REAL,
    amount      REAL NOT NULL,
    discount    REAL NOT NULL DEFAULT 0,
    is_weight   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (receipt_id, line_no)
);
CREATE INDEX IF NOT EXISTS items_name ON items(name);

CREATE TABLE IF NOT EXISTS kv (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def connect(path: Path) -> sqlite3.Connection:
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(SCHEMA)
    return conn


def get_kv(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
    return None if row is None else str(row["value"])


def set_kv(conn: sqlite3.Connection, key: str, value: str) -> None:
    with conn:
        conn.execute(
            "INSERT INTO kv(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def receipt_exists(conn: sqlite3.Connection, receipt_id: str) -> bool:
    return conn.execute("SELECT 1 FROM receipts WHERE id = ?", (receipt_id,)).fetchone() is not None


def to_local(value: str, tz: str) -> str:
    """Normalise an API timestamp to naive local time so SQLite date functions group correctly."""
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is not None:
        dt = dt.astimezone(ZoneInfo(tz)).replace(tzinfo=None)
    return dt.replace(microsecond=0).isoformat()


def _store_name(summary: dict[str, Any], detail: dict[str, Any]) -> str:
    store = detail.get("store") or {}
    if isinstance(store, dict):
        parts = [store.get("name"), store.get("address"), store.get("locality")]
        name = ", ".join(str(p) for p in parts if p)
        if name:
            return name
    return str(summary.get("storeCode") or "")


def save_receipt(
    conn: sqlite3.Connection, summary: dict[str, Any], detail: dict[str, Any], tz: str
) -> None:
    receipt_id = str(summary["id"])
    total = parse_number(summary.get("totalAmount"))
    if total is None:
        total = parse_number(detail.get("totalAmount")) or 0.0
    currency = summary.get("currency") or detail.get("currency") or {}
    with conn:
        conn.execute("DELETE FROM receipts WHERE id = ?", (receipt_id,))
        conn.execute(
            "INSERT INTO receipts(id, date, store_code, store_name, total, currency,"
            " raw_summary, raw_detail, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                receipt_id,
                to_local(str(summary.get("date") or detail["date"]), tz),
                str(summary.get("storeCode") or ""),
                _store_name(summary, detail),
                total,
                str(currency.get("code", "")) if isinstance(currency, dict) else str(currency),
                json.dumps(summary, ensure_ascii=False),
                json.dumps(detail, ensure_ascii=False),
                datetime.now().replace(microsecond=0).isoformat(),
            ),
        )
        _write_items(conn, receipt_id, detail)


def _write_items(conn: sqlite3.Connection, receipt_id: str, detail: dict[str, Any]) -> None:
    parsed = parse_receipt(detail)
    conn.execute("DELETE FROM items WHERE receipt_id = ?", (receipt_id,))
    conn.executemany(
        "INSERT INTO items(receipt_id, line_no, name, code, quantity, unit_price, amount,"
        " discount, is_weight) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                receipt_id,
                i,
                it.name,
                it.code,
                it.quantity,
                it.unit_price,
                it.amount,
                it.discount,
                int(it.is_weight),
            )
            for i, it in enumerate(parsed.items)
        ],
    )
    conn.execute(
        "UPDATE receipts SET parse_source = ?, items_total = ?, discount = ? WHERE id = ?",
        (
            parsed.source,
            round(sum(it.amount for it in parsed.items), 2),
            round(sum(it.discount for it in parsed.items), 2),
            receipt_id,
        ),
    )


def reparse_all(conn: sqlite3.Connection) -> int:
    """Re-derive items from the stored raw responses (after a parser change)."""
    rows = conn.execute("SELECT id, raw_detail FROM receipts").fetchall()
    with conn:
        for row in rows:
            _write_items(conn, row["id"], json.loads(row["raw_detail"]))
    return len(rows)
