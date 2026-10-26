#!/usr/bin/env bash
# One-time Codespace setup: uv, Python deps (incl. Playwright for login), Chromium.
set -euo pipefail
cd "$(dirname "$0")/.."

pip install --user --quiet uv
export PATH="$HOME/.local/bin:$PATH"

uv sync --extra login
uv run playwright install chromium
sudo "$PWD/.venv/bin/playwright" install-deps chromium

[ -f .env ] || cp .env.example .env
