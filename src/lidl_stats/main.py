"""FastAPI app: JSON stats API + the static mobile web UI."""

import asyncio
import contextlib
import hmac
import json
import logging
import sqlite3
import threading
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from pathlib import Path
from typing import Annotated, Any, Literal

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from lidl_stats import db, stats
from lidl_stats.config import Settings, get_settings
from lidl_stats.sync import is_running, sync_once

log = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).parent / "static"


async def _periodic_sync(settings: Settings) -> None:
    while True:
        result = await asyncio.to_thread(sync_once, settings)
        log.info("Szinkron: %d új, hiba: %s", result.new, result.error or "-")
        await asyncio.sleep(settings.sync_interval_hours * 3600)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        db.connect(settings.db_path).close()  # create schema up front
        task = None
        if settings.sync_interval_hours > 0 and (settings.refresh_token or _has_stored_token()):
            task = asyncio.create_task(_periodic_sync(settings))
        yield
        if task:
            task.cancel()

    def _has_stored_token() -> bool:
        conn = db.connect(settings.db_path)
        try:
            return bool(db.get_kv(conn, "refresh_token"))
        finally:
            conn.close()

    app = FastAPI(title="Lidl statisztikák", lifespan=lifespan)

    @app.middleware("http")
    async def require_token(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if settings.app_token and request.url.path.startswith("/api/"):
            given = request.headers.get("x-app-token", "")
            if not hmac.compare_digest(given, settings.app_token):
                return JSONResponse({"detail": "Hibás vagy hiányzó hozzáférési kód"}, 401)
        return await call_next(request)

    def get_conn() -> Iterator[sqlite3.Connection]:
        conn = db.connect(settings.db_path)
        try:
            yield conn
        finally:
            conn.close()

    Conn = Annotated[sqlite3.Connection, Depends(get_conn)]

    def get_period(
        start: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}-\d{2}$")] = None,
        end: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}-\d{2}$")] = None,
    ) -> stats.Period:
        return stats.Period(start, end)

    P = Annotated[stats.Period, Depends(get_period)]

    @app.get("/api/status")
    def status(conn: Conn) -> dict[str, Any]:
        return {
            "receipts": conn.execute("SELECT COUNT(*) FROM receipts").fetchone()[0],
            "last_sync": db.get_kv(conn, "last_sync"),
            "last_sync_error": db.get_kv(conn, "last_sync_error") or "",
            "syncing": is_running(),
            "has_token": bool(settings.refresh_token or db.get_kv(conn, "refresh_token")),
        }

    @app.post("/api/sync", status_code=202)
    def start_sync(full: bool = False) -> dict[str, bool]:
        if not is_running():
            threading.Thread(target=sync_once, args=(settings, full), daemon=True).start()
        return {"syncing": True}

    @app.get("/api/summary")
    def summary(conn: Conn, period: P) -> dict[str, Any]:
        return stats.summary(conn, period)

    @app.get("/api/monthly")
    def monthly(conn: Conn, period: P) -> list[dict[str, Any]]:
        return stats.monthly(conn, period)

    @app.get("/api/weekday-hour")
    def weekday_hour(conn: Conn, period: P) -> list[dict[str, Any]]:
        return stats.weekday_hour(conn, period)

    @app.get("/api/top-products")
    def top_products(
        conn: Conn,
        period: P,
        by: Literal["spend", "count"] = "spend",
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
    ) -> list[dict[str, Any]]:
        return stats.top_products(conn, period, by, limit)

    @app.get("/api/stores")
    def stores(conn: Conn, period: P) -> list[dict[str, Any]]:
        return stats.stores(conn, period)

    @app.get("/api/products")
    def products(conn: Conn, q: Annotated[str, Query(min_length=1)]) -> list[dict[str, Any]]:
        return stats.search_products(conn, q)

    @app.get("/api/products/history")
    def product_history(conn: Conn, name: str) -> list[dict[str, Any]]:
        return stats.price_history(conn, name)

    @app.get("/api/receipts")
    def receipts(
        conn: Conn,
        period: P,
        limit: Annotated[int, Query(ge=1, le=200)] = 30,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> list[dict[str, Any]]:
        return stats.receipts(conn, period, limit, offset)

    @app.get("/api/receipts/{receipt_id}/items")
    def receipt_items(conn: Conn, receipt_id: str) -> list[dict[str, Any]]:
        return stats.receipt_items(conn, receipt_id)

    @app.get("/api/receipts/{receipt_id}/raw")
    def receipt_raw(conn: Conn, receipt_id: str) -> dict[str, Any]:
        """The untouched API response - useful for fixing the parser."""
        row = conn.execute(
            "SELECT raw_summary, raw_detail FROM receipts WHERE id = ?", (receipt_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(404, "Nincs ilyen blokk")
        return {"summary": json.loads(row[0]), "detail": json.loads(row[1])}

    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    return app


def run() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)
