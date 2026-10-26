import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from lidl_stats.config import Settings
from lidl_stats.lidl_client import LidlClient

FIXTURES = Path(__file__).parent / "fixtures"

TICKETS: list[dict[str, Any]] = [
    {
        "id": "T3",
        "date": "2026-10-20T16:30:00+02:00",
        "totalAmount": 2196,
        "currency": {"code": "HUF"},
        "storeCode": "HU0001",
    },
    {
        "id": "T2",
        "date": "2026-09-14T08:05:00Z",
        "totalAmount": 1000,
        "currency": {"code": "HUF"},
        "storeCode": "HU0002",
    },
    {
        "id": "T1",
        "date": "2025-12-01T18:10:00+01:00",
        "totalAmount": 658,
        "currency": {"code": "HUF"},
        "storeCode": "HU0001",
    },
]


def _detail(ticket_id: str) -> dict[str, Any]:
    store = {"name": "Lidl Budapest", "address": "Fő utca 1.", "locality": "Budapest"}
    if ticket_id == "T3":
        html = (FIXTURES / "receipt_v3.html").read_text()
        return {"id": "T3", "store": store, "htmlPrintedReceipt": html}
    if ticket_id == "T2":
        return {
            "id": "T2",
            "store": {"name": "Lidl Debrecen"},
            "itemsLine": [
                {
                    "name": "TEJ 2,8% 1L",
                    "currentUnitPrice": "349",
                    "quantity": "1",
                    "originalAmount": "349",
                },
                {
                    "name": "KÁVÉ",
                    "currentUnitPrice": "651",
                    "quantity": "1",
                    "originalAmount": "651",
                },
            ],
        }
    return {
        "id": "T1",
        "store": store,
        "itemsLine": [
            {
                "name": "TEJ 2,8% 1L",
                "currentUnitPrice": "299",
                "quantity": "2",
                "originalAmount": "598",
            },
            {"name": "ZACSKÓ", "currentUnitPrice": "60", "quantity": "1", "originalAmount": "60"},
        ],
    }


class FakeLidl:
    """In-memory stand-in for the Lidl Plus HTTP API."""

    def __init__(self, page_size: int = 2) -> None:
        self.page_size = page_size
        self.tickets = list(TICKETS)
        self.requests: list[str] = []
        self.token_counter = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(f"{request.method} {request.url.path}?{request.url.query.decode()}")
        path = request.url.path
        if path == "/connect/token":
            self.token_counter += 1
            return httpx.Response(
                200,
                json={
                    "access_token": "access",
                    "expires_in": 3600,
                    "refresh_token": f"rotated-{self.token_counter}",
                },
            )
        if request.headers.get("authorization") != "Bearer access":
            return httpx.Response(401)
        if path == "/api/v2/HU/tickets":
            page = int(request.url.params["pageNumber"])
            chunk = self.tickets[(page - 1) * self.page_size : page * self.page_size]
            return httpx.Response(
                200,
                json={"tickets": chunk, "totalCount": len(self.tickets), "size": self.page_size},
            )
        if path.startswith("/api/v3/HU/tickets/"):
            return httpx.Response(200, json=_detail(path.rsplit("/", 1)[1]))
        return httpx.Response(404, text=json.dumps({"path": path}))


@pytest.fixture
def fake_lidl() -> FakeLidl:
    return FakeLidl()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        refresh_token="seed-token",
        country="HU",
        language="hu",
        app_version="16.45.5",
        db_path=tmp_path / "lidl.sqlite3",
        timezone="Europe/Budapest",
        sync_interval_hours=0,
        app_token="",
        host="127.0.0.1",
        port=8000,
    )


@pytest.fixture
def client_factory(fake_lidl: FakeLidl) -> Callable[..., LidlClient]:
    def make(**kwargs: Any) -> LidlClient:
        return LidlClient(
            refresh_token=kwargs.pop("refresh_token", "seed-token"),
            country="HU",
            language="hu",
            app_version="16.45.5",
            http=httpx.Client(transport=httpx.MockTransport(fake_lidl.handler)),
            **kwargs,
        )

    return make
