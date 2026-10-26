"""Download new receipts from Lidl Plus into the local database."""

import argparse
import logging
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime

from lidl_stats import db
from lidl_stats.config import Settings, get_settings
from lidl_stats.lidl_client import LidlClient, LidlError

log = logging.getLogger(__name__)

# The refresh token may be rotated on renewal; the latest one lives in the database.
# The env token it was seeded from is remembered so that pasting a new token into the
# environment (e.g. after the old one expired) takes precedence again.
_TOKEN_KEY = "refresh_token"
_SEED_KEY = "refresh_token_seed"

_lock = threading.Lock()


@dataclass
class SyncResult:
    new: int = 0
    failed: list[str] = field(default_factory=list)
    error: str = ""


def is_running() -> bool:
    return _lock.locked()


def current_refresh_token(conn: sqlite3.Connection, settings: Settings) -> str:
    stored = db.get_kv(conn, _TOKEN_KEY)
    if settings.refresh_token and db.get_kv(conn, _SEED_KEY) != settings.refresh_token:
        db.set_kv(conn, _SEED_KEY, settings.refresh_token)
        db.set_kv(conn, _TOKEN_KEY, settings.refresh_token)
        return settings.refresh_token
    return stored or settings.refresh_token


def make_client(conn: sqlite3.Connection, settings: Settings) -> LidlClient:
    return LidlClient(
        refresh_token=current_refresh_token(conn, settings),
        country=settings.country,
        language=settings.language,
        app_version=settings.app_version,
        on_refresh_token=lambda token: db.set_kv(conn, _TOKEN_KEY, token),
    )


def sync(
    conn: sqlite3.Connection,
    client: LidlClient,
    settings: Settings,
    full: bool = False,
    delay: float = 0.3,
) -> SyncResult:
    result = SyncResult()
    if not _lock.acquire(blocking=False):
        result.error = "Már fut egy szinkronizálás"
        return result
    try:
        tickets = client.list_tickets(
            is_known=None if full else lambda tid: db.receipt_exists(conn, tid)
        )
        for summary in tickets:
            ticket_id = str(summary["id"])
            if not full and db.receipt_exists(conn, ticket_id):
                continue
            try:
                detail = client.ticket(ticket_id)
                db.save_receipt(conn, summary, detail, settings.timezone)
                result.new += 1
            except (LidlError, KeyError, ValueError) as exc:
                log.warning("Blokk %s letöltése sikertelen: %s", ticket_id, exc)
                result.failed.append(ticket_id)
            time.sleep(delay)
    except LidlError as exc:
        result.error = str(exc)
    finally:
        db.set_kv(conn, "last_sync", datetime.now().replace(microsecond=0).isoformat())
        db.set_kv(conn, "last_sync_error", result.error)
        _lock.release()
    return result


def sync_once(settings: Settings, full: bool = False) -> SyncResult:
    conn = db.connect(settings.db_path)
    try:
        with make_client(conn, settings) as client:
            return sync(conn, client, settings, full=full)
    except LidlError as exc:
        db.set_kv(conn, "last_sync_error", str(exc))
        return SyncResult(error=str(exc))
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Lidl Plus blokkok letöltése")
    parser.add_argument("--full", action="store_true", help="minden blokk újratöltése")
    parser.add_argument(
        "--reparse", action="store_true", help="tárolt blokkok újraelemzése letöltés nélkül"
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    if args.reparse:
        conn = db.connect(settings.db_path)
        print(f"{db.reparse_all(conn)} blokk újraelemezve")
        return
    result = sync_once(settings, full=args.full)
    print(f"Új blokkok: {result.new}, sikertelen: {len(result.failed)}")
    if result.error:
        raise SystemExit(f"Hiba: {result.error}")
