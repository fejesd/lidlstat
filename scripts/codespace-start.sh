#!/usr/bin/env bash
# (Re)start the web server in the background, with settings from .env.
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:$PATH"

pkill -f "\.venv/bin/lidl-stats$" || true
set -a
# shellcheck disable=SC1091
[ -f .env ] && . ./.env
set +a
nohup .venv/bin/lidl-stats > /tmp/lidl-stats.log 2>&1 &
echo "A szerver fut: 8000-es port (napló: /tmp/lidl-stats.log)"
