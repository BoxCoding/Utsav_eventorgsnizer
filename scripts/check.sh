#!/usr/bin/env bash
# Every quality gate in one go: lint, backend + frontend tests with coverage, and the
# WCAG 2.1 AA audit (needs the app running on :8101 and Chrome installed).
set -euo pipefail
cd "$(dirname "$0")/.."
.venv/bin/ruff check .
.venv/bin/python -m pytest -q --cov=backend --cov-report=term:skip-covered
npm run --silent lint
npm test --silent
if curl -sf localhost:8101/api/health >/dev/null; then npm run --silent test:a11y; else
  echo "Skipping accessibility audit: start the app on :8101 first"; fi
