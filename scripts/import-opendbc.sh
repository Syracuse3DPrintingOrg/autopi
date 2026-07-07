#!/usr/bin/env bash
# Fetch comma.ai's opendbc DBC collection and import it into AutoPi's database.
#
# opendbc (https://github.com/commaai/opendbc) is MIT-licensed and is the
# largest open collection of vehicle CAN databases. This clones it into the
# app's data directory (so the container can read it) and asks the running app
# to import every .dbc file. Re-runnable.
#
#   ./scripts/import-opendbc.sh            # on a server / dev box
#   sudo ./scripts/import-opendbc.sh       # on a Pi appliance
set -euo pipefail

REPO_DIR="${REPO_DIR:-/opt/autopi-src}"
[ -d "$REPO_DIR/service/data" ] || REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DATA_DIR="${REPO_DIR}/service/data"
SRC="${DATA_DIR}/opendbc-src"
APP_URL="${APP_URL:-http://127.0.0.1:9284}"
# Where the DBC dir is as the app (container) sees it. The data dir is mounted
# at /app/data, so opendbc-src/opendbc/dbc maps to /app/data/opendbc-src/...
IN_APP_DBC="${IN_APP_DBC:-/app/data/opendbc-src/opendbc/dbc}"

echo "Fetching opendbc (MIT) into ${SRC}"
if [ -d "${SRC}/.git" ]; then
  git -C "${SRC}" pull --ff-only || echo "pull failed; using what is on disk"
else
  git clone --depth 1 https://github.com/commaai/opendbc "${SRC}"
fi

echo "Importing DBC files into the database via ${APP_URL}"
curl -fsS -X POST "${APP_URL}/can/dbc/import-directory" \
  -H "Content-Type: application/json" \
  -d "{\"path\": \"${IN_APP_DBC}\", \"source\": \"opendbc\", \"license\": \"MIT\"}" \
  && echo "" && echo "Done. Open Settings to browse the imported databases."
