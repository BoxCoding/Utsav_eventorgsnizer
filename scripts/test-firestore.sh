#!/usr/bin/env bash
# Run the full test suite against the Firestore emulator (needs gcloud + Java 17+).
set -euo pipefail
cd "$(dirname "$0")/.."
PORT=8789
gcloud emulators firestore start --host-port=127.0.0.1:$PORT --quiet >/tmp/utsav-fs-emulator.log 2>&1 &
EMU=$!
trap 'kill $EMU 2>/dev/null' EXIT
for _ in $(seq 1 40); do curl -s 127.0.0.1:$PORT >/dev/null && break; sleep 1; done
UTSAV_STORE=firestore FIRESTORE_EMULATOR_HOST=127.0.0.1:$PORT .venv/bin/python -m pytest -q "$@"
