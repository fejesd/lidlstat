from collections.abc import Callable

from lidl_stats import db, stats
from lidl_stats.config import Settings
from lidl_stats.lidl_client import LidlClient
from lidl_stats.sync import current_refresh_token, sync

from .conftest import FakeLidl


def test_sync_then_stats(
    settings: Settings, fake_lidl: FakeLidl, client_factory: Callable[..., LidlClient]
) -> None:
    conn = db.connect(settings.db_path)
    with client_factory() as client:
        result = sync(conn, client, settings, delay=0)
    assert (result.new, result.failed, result.error) == (3, [], "")

    # UTC timestamp converted to Budapest local time
    row = conn.execute("SELECT date, store_name FROM receipts WHERE id = 'T2'").fetchone()
    assert row["date"] == "2026-09-14T10:05:00"
    assert row["store_name"] == "Lidl Debrecen"

    everything = stats.Period()
    s = stats.summary(conn, everything)
    assert s["receipts"] == 3
    assert s["spend"] == 2196 + 1000 + 658
    assert s["savings"] == 100
    assert s["currency"] == "HUF"
    assert s["items"] == 8

    # T3 parsed items: 329 + 329 + 739.77 + 898 - 100 = 2195.77 -> within tolerance
    assert s["mismatched"] == 0

    assert [m["month"] for m in stats.monthly(conn, everything)] == [
        "2025-12",
        "2026-09",
        "2026-10",
    ]

    top = stats.top_products(conn, everything, by="count")
    assert top[0]["name"] == "TEJ 2,8% 1L"
    assert top[0]["purchases"] == 3

    history = stats.price_history(conn, "TEJ 2,8% 1L")
    assert [h["unit_price"] for h in history] == [299, 349, 329, 329]

    period = stats.Period(start="2026-09-01", end="2026-09-30")
    assert stats.summary(conn, period)["receipts"] == 1

    heat = stats.weekday_hour(conn, everything)
    # 2026-10-20 is a Tuesday (weekday 1), 16:30 local
    assert {"weekday": 1, "hour": 16, "receipts": 1, "spend": 2196.0} in heat

    assert [p["name"] for p in stats.search_products(conn, "tej")] == ["TEJ 2,8% 1L"]

    # Milk is the only product bought more than once: 299 (2025-12) -> 329 (2026-10)
    changes = stats.price_changes(conn, everything)
    assert changes["products"] == 1
    assert changes["inflation"] == 10.0
    assert [r["name"] for r in changes["increases"]] == ["TEJ 2,8% 1L"]
    assert changes["increases"][0]["first_price"] == 299
    assert changes["increases"][0]["last_price"] == 329
    assert changes["decreases"] == []

    # From September only 349 -> 329 remains
    recent = stats.price_changes(conn, stats.Period(start="2026-09-01"))
    assert recent["products"] == 1
    assert recent["decreases"][0]["change_pct"] == -5.7

    # Both October purchases are on the same day: too close to count as a price change
    assert stats.price_changes(conn, stats.Period(start="2026-10-01"))["products"] == 0


def test_incremental_sync_stops_paging(
    settings: Settings, fake_lidl: FakeLidl, client_factory: Callable[..., LidlClient]
) -> None:
    conn = db.connect(settings.db_path)
    with client_factory() as client:
        sync(conn, client, settings, delay=0)
    fake_lidl.tickets.insert(
        0,
        {
            "id": "T4",
            "date": "2026-10-25T10:00:00+02:00",
            "totalAmount": 329,
            "currency": {"code": "HUF"},
            "storeCode": "HU0001",
        },
    )
    fake_lidl.requests.clear()
    with client_factory() as client:
        result = sync(conn, client, settings, delay=0)
    assert result.new == 1
    list_calls = [r for r in fake_lidl.requests if "/v2/HU/tickets" in r]
    assert len(list_calls) == 1  # first page already contains known tickets


def test_rotated_refresh_token_is_persisted(
    settings: Settings, client_factory: Callable[..., LidlClient]
) -> None:
    conn = db.connect(settings.db_path)
    token = current_refresh_token(conn, settings)
    assert token == "seed-token"
    with client_factory(
        refresh_token=token, on_refresh_token=lambda t: db.set_kv(conn, "refresh_token", t)
    ) as client:
        sync(conn, client, settings, delay=0)
    assert current_refresh_token(conn, settings) == "rotated-1"

    # A new token in the environment wins over the stored one
    new_settings = Settings(**{**settings.__dict__, "refresh_token": "fresh-env-token"})
    assert current_refresh_token(conn, new_settings) == "fresh-env-token"


def test_reparse_all(settings: Settings, client_factory: Callable[..., LidlClient]) -> None:
    conn = db.connect(settings.db_path)
    with client_factory() as client:
        sync(conn, client, settings, delay=0)
    conn.execute("DELETE FROM items")
    conn.commit()
    assert db.reparse_all(conn) == 3
    assert conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 8
