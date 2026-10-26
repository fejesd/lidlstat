"""One-time login to obtain a Lidl Plus refresh token.

Lidl's login page is protected by reCAPTCHA, so it cannot be automated headlessly.
Instead the user logs in themselves in a real browser window and we only capture the
OAuth authorization code from the final redirect to ``com.lidlplus.app://callback``.

Run it on a machine with a desktop (not inside the server container):

    uv run --extra login lidl-stats-login            # opens a Chromium window
    uv run lidl-stats-login --manual                 # any browser, copy-paste the code
"""

import argparse
import base64
import hashlib
import re
import secrets
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

from lidl_stats.lidl_client import AUTH_API, CLIENT_ID, _basic_auth

REDIRECT_URI = "com.lidlplus.app://callback"
SCOPES = "openid profile offline_access lpprofile lpapis"
_CODE_RE = re.compile(r"[?&]code=([^&#\s]+)")


def make_pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def auth_url(challenge: str, country: str, language: str) -> str:
    params = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "scope": SCOPES,
        "redirect_uri": REDIRECT_URI,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "Country": country.upper(),
        "language": f"{language.lower()}-{country.upper()}",
    }
    return f"{AUTH_API}/connect/authorize?{urlencode(params)}"


def extract_code(text: str) -> str | None:
    text = text.strip()
    if match := _CODE_RE.search(text):
        return match.group(1)
    return text if re.fullmatch(r"[A-Za-z0-9\-_.]{16,}", text) else None


def exchange_code(code: str, verifier: str) -> dict[str, Any]:
    resp = httpx.post(
        f"{AUTH_API}/connect/token",
        headers={
            "Authorization": _basic_auth(),
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": verifier,
        },
        timeout=30,
    )
    if resp.status_code != 200:
        raise SystemExit(f"Token csere sikertelen: {resp.status_code} {resp.text}")
    result: dict[str, Any] = resp.json()
    return result


def _browser_login(url: str, timeout_s: int) -> str:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SystemExit(
            "A Playwright nincs telepítve. Használd: uv run --extra login lidl-stats-login\n"
            "(első alkalommal: uv run --extra login playwright install chromium)\n"
            "vagy a böngésző nélküli módot: lidl-stats-login --manual"
        ) from None

    code: str | None = None

    def capture(target: str) -> None:
        nonlocal code
        if code is None and target.startswith(REDIRECT_URI):
            code = extract_code(target)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        page.on("request", lambda req: capture(req.url))
        page.on("response", lambda resp: capture(resp.headers.get("location", "")))
        page.goto(url)
        print("Jelentkezz be a megnyílt böngészőablakban (telefonszám/e-mail, jelszó, kód).")
        deadline = time.monotonic() + timeout_s
        while code is None and time.monotonic() < deadline:
            page.wait_for_timeout(500)
        browser.close()
    if code is None:
        raise SystemExit("Nem sikerült elkapni a bejelentkezési kódot (időtúllépés).")
    return code


def _manual_login(url: str) -> str:
    print(
        "1. Nyisd meg ezt a linket egy asztali böngészőben, előtte nyisd meg a\n"
        "   Fejlesztői eszközök > Network (Hálózat) fület, és kapcsold be a 'Preserve log'-ot:\n\n"
        f"   {url}\n\n"
        "2. Jelentkezz be. A végén a böngésző egy com.lidlplus.app://callback?code=...\n"
        "   címre próbál átirányítani, ami hibát ad - ez így rendben van.\n"
        "3. Másold ki ezt a címet (vagy csak a code= utáni részt) a Network fülről,\n"
        "   és illeszd be ide."
    )
    code = extract_code(input("\nCallback URL vagy kód: "))
    if not code:
        raise SystemExit("Nem találtam kódot a beillesztett szövegben.")
    return code


def write_env(path: Path, token: str) -> None:
    lines = path.read_text().splitlines() if path.exists() else []
    lines = [line for line in lines if not line.startswith("LIDL_REFRESH_TOKEN=")]
    lines.append(f"LIDL_REFRESH_TOKEN={token}")
    path.write_text("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Lidl Plus bejelentkezés (refresh token)")
    parser.add_argument("--country", default="HU")
    parser.add_argument("--language", default="hu")
    parser.add_argument("--manual", action="store_true", help="böngésző-automatizálás nélkül")
    parser.add_argument("--timeout", type=int, default=600, help="várakozás másodpercben")
    parser.add_argument("--env-file", type=Path, help="írja be a tokent ebbe a .env fájlba")
    args = parser.parse_args()

    verifier, challenge = make_pkce()
    url = auth_url(challenge, args.country, args.language)
    code = _manual_login(url) if args.manual else _browser_login(url, args.timeout)
    token = exchange_code(code, verifier)["refresh_token"]

    if args.env_file:
        write_env(args.env_file, token)
        print(f"A refresh token bekerült ide: {args.env_file}")
    else:
        print("\nRefresh token (tedd a .env fájlba LIDL_REFRESH_TOKEN néven):\n", file=sys.stderr)
        print(token)
