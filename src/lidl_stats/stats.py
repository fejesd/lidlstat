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


def price_changes(conn: sqlite3.Connection, period: Period, min_days: int = 28) -> dict[str, Any]:
    """Shelf-price change per product (first vs. last purchase in the period) and the
    spend-weighted average of those changes - a "personal inflation" figure.

    Only products bought at least twice, at least ``min_days`` apart, are counted.
    Unit prices are pre-discount, so coupons don't show up as price drops.
    """
    where, params = period.where()
    rows = _rows(
        conn,
        f"""
        WITH p AS (
            SELECT i.name, r.date,
                   COALESCE(i.unit_price, i.amount / NULLIF(i.quantity, 0)) AS unit_price,
                   i.amount - i.discount AS spend, i.is_weight
            FROM items i JOIN receipts r ON r.id = i.receipt_id
            WHERE {where}
        ),
        priced AS (SELECT * FROM p WHERE unit_price > 0),
        ranked AS (
            SELECT name, unit_price,
                   ROW_NUMBER() OVER (PARTITION BY name ORDER BY date, unit_price) AS rn_first,
                   ROW_NUMBER() OVER (PARTITION BY name ORDER BY date DESC, unit_price DESC)
                       AS rn_last
            FROM priced
        ),
        agg AS (
            SELECT name, COUNT(*) AS purchases, MIN(date) AS first_date, MAX(date) AS last_date,
                   SUM(spend) AS spend, MAX(is_weight) AS is_weight
            FROM priced GROUP BY name
            HAVING purchases >= 2 AND julianday(last_date) - julianday(first_date) >= ?
        )
        SELECT a.name, a.purchases, a.first_date, a.last_date, ROUND(a.spend, 2) AS spend,
               a.is_weight, f.unit_price AS first_price, l.unit_price AS last_price
        FROM agg a
        JOIN ranked f ON f.name = a.name AND f.rn_first = 1
        JOIN ranked l ON l.name = a.name AND l.rn_last = 1
        """,
        [*params, min_days],
    )
    for row in rows:
        row["change_pct"] = round((row["last_price"] / row["first_price"] - 1) * 100, 1)
    total_spend = sum(r["spend"] for r in rows)
    inflation = (
        round(sum(r["change_pct"] * r["spend"] for r in rows) / total_spend, 1)
        if total_spend > 0
        else None
    )
    changed = [r for r in rows if r["change_pct"] != 0]
    return {
        "inflation": inflation,
        "products": len(rows),
        "first_date": min((r["first_date"] for r in rows), default=None),
        "last_date": max((r["last_date"] for r in rows), default=None),
        "increases": sorted(
            (r for r in changed if r["change_pct"] > 0), key=lambda r: -r["change_pct"]
        ),
        "decreases": sorted(
            (r for r in changed if r["change_pct"] < 0), key=lambda r: r["change_pct"]
        ),
    }
