from collections.abc import Callable

from fastapi.testclient import TestClient

from lidl_stats import db
from lidl_stats.config import Settings
from lidl_stats.lidl_client import LidlClient
from lidl_stats.main import create_app
from lidl_stats.sync import sync


def _seeded(settings: Settings, client_factory: Callable[..., LidlClient]) -> None:
    conn = db.connect(settings.db_path)
    with client_factory() as client:
        sync(conn, client, settings, delay=0)
    conn.close()


def test_endpoints(settings: Settings, client_factory: Callable[..., LidlClient]) -> None:
    _seeded(settings, client_factory)
    with TestClient(create_app(settings)) as http:
        assert http.get("/api/status").json()["receipts"] == 3
        assert http.get("/api/summary?start=2026-01-01").json()["receipts"] == 2
        assert http.get("/api/summary?start=bad").status_code == 422
        assert len(http.get("/api/monthly").json()) == 3
        assert http.get("/api/top-products?by=count&limit=1").json()[0]["purchases"] == 3
        assert http.get("/api/products?q=k").status_code == 200
        hist = http.get("/api/products/history", params={"name": "TEJ 2,8% 1L"}).json()
        assert len(hist) == 4
        assert http.get("/api/price-changes").json()["inflation"] == 10.0
        receipts = http.get("/api/receipts").json()
        assert receipts[0]["id"] == "T3"
        assert len(http.get("/api/receipts/T3/items").json()) == 4
        assert "htmlPrintedReceipt" in http.get("/api/receipts/T3/raw").json()["detail"]
        assert http.get("/api/receipts/nope/raw").status_code == 404
        page = http.get("/")
        assert page.status_code == 200 and "Vásárlásaim" in page.text


def test_app_token(settings: Settings) -> None:
    secured = Settings(**{**settings.__dict__, "app_token": "titok"})
    with TestClient(create_app(secured)) as http:
        assert http.get("/api/status").status_code == 401
        assert http.get("/api/status", headers={"X-App-Token": "titok"}).status_code == 200
        # static UI stays reachable so it can ask for the code
        assert http.get("/").status_code == 200
