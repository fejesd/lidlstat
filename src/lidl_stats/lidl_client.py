"""Minimal client for the (unofficial, reverse-engineered) Lidl Plus API."""

import base64
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

AUTH_API = "https://accounts.lidl.com"
TICKETS_API = "https://tickets.lidlplus.com/api"
CLIENT_ID = "LidlPlusNativeClient"


class LidlError(Exception):
    pass


class LidlAuthError(LidlError):
    pass


def _basic_auth() -> str:
    return "Basic " + base64.b64encode(f"{CLIENT_ID}:secret".encode()).decode()


class LidlClient:
    """Renews access tokens from a refresh token and fetches receipts ("tickets")."""

    def __init__(
        self,
        refresh_token: str,
        country: str,
        language: str,
        app_version: str,
        on_refresh_token: Callable[[str], None] | None = None,
        http: httpx.Client | None = None,
    ) -> None:
        if not refresh_token:
            raise LidlAuthError("Nincs refresh token. Futtasd: lidl-stats-login")
        self._refresh_token = refresh_token
        self._country = country.upper()
        self._language = language.lower()
        self._app_version = app_version
        self._on_refresh_token = on_refresh_token
        self._access_token = ""
        self._expires = datetime.min.replace(tzinfo=UTC)
        self._http = http or httpx.Client(timeout=httpx.Timeout(30.0, connect=10.0))

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "LidlClient":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _renew_token(self) -> None:
        resp = self._http.post(
            f"{AUTH_API}/connect/token",
            headers={
                "Authorization": _basic_auth(),
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"refresh_token": self._refresh_token, "grant_type": "refresh_token"},
        )
        if resp.status_code != 200:
            raise LidlAuthError(f"Token megújítás sikertelen: {resp.status_code} {resp.text}")
        data = resp.json()
        self._access_token = data["access_token"]
        # Renew a minute early so a request never goes out with an expiring token.
        self._expires = datetime.now(UTC) + timedelta(seconds=int(data["expires_in"]) - 60)
        new_refresh = data.get("refresh_token")
        if new_refresh and new_refresh != self._refresh_token:
            self._refresh_token = new_refresh
            if self._on_refresh_token:
                self._on_refresh_token(new_refresh)

    def _headers(self) -> dict[str, str]:
        if not self._access_token or datetime.now(UTC) >= self._expires:
            self._renew_token()
        return {
            "Authorization": f"Bearer {self._access_token}",
            "App-Version": self._app_version,
            "Operating-System": "iOs",
            "App": "com.lidl.eci.lidl.plus",
            "Accept-Language": self._language,
        }

    def _get(self, url: str) -> dict[str, Any]:
        resp = self._http.get(url, headers=self._headers())
        if resp.status_code == 401:
            # Token revoked server-side before its expiry; retry once with a fresh one.
            self._access_token = ""
            resp = self._http.get(url, headers=self._headers())
        if resp.status_code != 200:
            raise LidlError(f"GET {url} -> {resp.status_code} {resp.text[:300]}")
        result: dict[str, Any] = resp.json()
        return result

    def list_tickets(self, is_known: Callable[[str], bool] | None = None) -> list[dict[str, Any]]:
        """Return ticket summaries, newest first.

        Paging stops after the first page that contains an already-known ticket, so an
        incremental sync only downloads what is new.
        """
        url = f"{TICKETS_API}/v2/{self._country}/tickets"
        tickets: list[dict[str, Any]] = []
        page, pages = 1, 1
        while page <= pages:
            data = self._get(f"{url}?pageNumber={page}&onlyFavorite=false")
            batch: list[dict[str, Any]] = list(data.get("tickets") or [])
            tickets.extend(batch)
            if page == 1:
                size = int(data.get("size") or len(batch) or 1)
                pages = (int(data.get("totalCount") or len(batch)) + size - 1) // size
            if not batch or (is_known and any(is_known(str(t["id"])) for t in batch)):
                break
            page += 1
        return tickets

    def ticket(self, ticket_id: str) -> dict[str, Any]:
        """Full receipt detail. v3 returns an HTML receipt; v2 the older JSON item list."""
        try:
            return self._get(f"{TICKETS_API}/v3/{self._country}/tickets/{ticket_id}")
        except LidlError:
            return self._get(f"{TICKETS_API}/v2/{self._country}/tickets/{ticket_id}")
