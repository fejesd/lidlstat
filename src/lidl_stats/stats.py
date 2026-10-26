"""Aggregations over the local receipt database."""

import sqlite3
from dataclasses import dataclass
from typing import Any, Literal

# A receipt whose parsed items don't add up to its total (beyond rounding) was
# probably mis-parsed; the UI flags these.
MISMATCH_TOLERANCE = 1.0


@dataclass(frozen=True)
class Period:
    start: str | None = None  # inclusive, 'YYYY-MM-DD'
    end: str | None = None  # inclusive, 'YYYY-MM-DD'

    def where(self, column: str = "r.date") -> tuple[str, list[str]]:
        clauses, params = [], []
        if self.start:
            clauses.append(f"{column} >= ?")
            params.append(self.start)
        if self.end:
            # Dates are stored with a time part, so compare against the next day's start.
            clauses.append(f"{column} < date(?, '+1 day')")
            params.append(self.end)
        return (" AND ".join(clauses) or "1=1"), params


def _rows(conn: sqlite3.Connection, sql: str, params: list[Any]) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def summary(conn: sqlite3.Connection, period: Period) -> dict[str, Any]:
    where, params = period.where()
    row = conn.execute(
        f"""
        SELECT COUNT(*) AS receipts,
               COALESCE(SUM(total), 0) AS spend,
               COALESCE(AVG(total), 0) AS avg_basket,
               COALESCE(SUM(discount), 0) AS savings,
               MIN(date) AS first_date,
               MAX(date) AS last_date,
               SUM(CASE WHEN ABS(items_total - discount - total) > ? THEN 1 ELSE 0 END)
                   AS mismatched,
               MAX(currency) AS currency
        FROM receipts r WHERE {where}
        """,
        [MISMATCH_TOLERANCE, *params],
    ).fetchone()
    result = dict(row)
    result["mismatched"] = result["mismatched"] or 0
    items = conn.execute(
        f"SELECT COUNT(*) FROM items i JOIN receipts r ON r.id = i.receipt_id WHERE {where}",
        params,
    ).fetchone()[0]
    result["items"] = items
    return result


def monthly(conn: sqlite3.Connection, period: Period) -> list[dict[str, Any]]:
    where, params = period.where()
    return _rows(
        conn,
        f"""
        SELECT strftime('%Y-%m', date) AS month,
               ROUND(SUM(total), 2) AS spend,
               COUNT(*) AS receipts,
               ROUND(SUM(discount), 2) AS savings
        FROM receipts r WHERE {where}
        GROUP BY month ORDER BY month
        """,
        params,
    )


def weekday_hour(conn: sqlite3.Connection, period: Period) -> list[dict[str, Any]]:
    """Visit counts per (weekday, hour). weekday: 0 = Monday ... 6 = Sunday."""
    where, params = period.where()
    return _rows(
        conn,
        f"""
        SELECT (CAST(strftime('%w', date) AS INTEGER) + 6) % 7 AS weekday,
               CAST(strftime('%H', date) AS INTEGER) AS hour,
               COUNT(*) AS receipts,
               ROUND(SUM(total), 2) AS spend
        FROM receipts r WHERE {where}
        GROUP BY weekday, hour ORDER BY weekday, hour
        """,
        params,
    )


def top_products(
    conn: sqlite3.Connection,
    period: Period,
    by: Literal["spend", "count"] = "spend",
    limit: int = 20,
) -> list[dict[str, Any]]:
    where, params = period.where()
    order = "spend DESC" if by == "spend" else "purchases DESC, spend DESC"
    return _rows(
        conn,
        f"""
        SELECT i.name,
               ROUND(SUM(i.amount - i.discount), 2) AS spend,
               COUNT(DISTINCT i.receipt_id) AS purchases,
               ROUND(SUM(i.quantity), 3) AS quantity,
               MAX(i.is_weight) AS is_weight
        FROM items i JOIN receipts r ON r.id = i.receipt_id
        WHERE {where}
        GROUP BY i.name ORDER BY {order} LIMIT ?
        """,
        [*params, limit],
    )


def search_products(conn: sqlite3.Connection, query: str, limit: int = 20) -> list[dict[str, Any]]:
    return _rows(
        conn,
        """
        SELECT name, COUNT(*) AS purchases FROM items
        WHERE name LIKE ? ESCAPE '\\'
        GROUP BY name ORDER BY purchases DESC LIMIT ?
        """,
        [
            "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%",
            limit,
        ],
    )


def price_history(conn: sqlite3.Connection, name: str) -> list[dict[str, Any]]:
    """Unit price per purchase; for weighed goods this is the price per kg."""
    return _rows(
        conn,
        """
        SELECT r.date,
               ROUND(COALESCE(i.unit_price, i.amount / NULLIF(i.quantity, 0)), 2) AS unit_price,
               i.quantity, i.amount, i.discount, i.is_weight
        FROM items i JOIN receipts r ON r.id = i.receipt_id
        WHERE i.name = ?
        ORDER BY r.date
        """,
        [name],
    )


def stores(conn: sqlite3.Connection, period: Period) -> list[dict[str, Any]]:
    where, params = period.where()
    return _rows(
        conn,
        f"""
        SELECT COALESCE(NULLIF(store_name, ''), store_code) AS store,
               COUNT(*) AS receipts, ROUND(SUM(total), 2) AS spend
        FROM receipts r WHERE {where}
        GROUP BY store ORDER BY receipts DESC
        """,
        params,
    )


def receipts(
    conn: sqlite3.Connection, period: Period, limit: int = 30, offset: int = 0
) -> list[dict[str, Any]]:
    where, params = period.where()
    return _rows(
        conn,
        f"""
        SELECT id, date, store_name, total, discount, currency,
               (SELECT COUNT(*) FROM items i WHERE i.receipt_id = r.id) AS items,
               ABS(items_total - discount - total) > {MISMATCH_TOLERANCE} AS mismatched
        FROM receipts r WHERE {where}
        ORDER BY date DESC LIMIT ? OFFSET ?
        """,
        [*params, limit, offset],
    )


def receipt_items(conn: sqlite3.Connection, receipt_id: str) -> list[dict[str, Any]]:
    return _rows(
        conn,
        "SELECT name, quantity, unit_price, amount, discount, is_weight FROM items"
        " WHERE receipt_id = ? ORDER BY line_no",
        [receipt_id],
    )
