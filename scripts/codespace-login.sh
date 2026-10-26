#!/usr/bin/env bash
# Opens the Lidl login in a Chromium window on the Codespace desktop (port 6080),
# saves the refresh token into .env and restarts the server.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "Nyisd meg a 'Távoli asztal' (6080-as) portot, jelszó: lidl"
echo "A megjelenő böngészőablakban jelentkezz be a Lidl Plus fiókodba."
DISPLAY="${DISPLAY:-:1}" .venv/bin/lidl-stats-login --env-file .env
bash scripts/codespace-start.sh
