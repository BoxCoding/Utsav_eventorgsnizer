#!/usr/bin/env bash
# Every quality gate in one go: lint, type check, backend + frontend tests with coverage,
# the WCAG 2.1 AA audit (app on :8101) and the journey test (offline-AI app on :8104).
set -euo pipefail
cd "$(dirname "$0")/.."
.venv/bin/ruff check .
.venv/bin/python -m pytest -q --cov=backend --cov-report=term:skip-covered
npm run --silent lint
npm run --silent typecheck
npm test --silent
if curl -sf localhost:8101/api/health >/dev/null; then npm run --silent test:a11y; else
  echo "Skipping accessibility audit: start the app on :8101 first"; fi
# Journey test on an offline-AI server (deterministic): UTSAV_OFFLINE=1 ... --port 8104
if curl -sf localhost:8104/api/health >/dev/null; then npm run --silent test:e2e; else
  echo "Skipping journey test: start an offline-AI server on :8104 first"; fi
