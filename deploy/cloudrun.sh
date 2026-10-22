#!/usr/bin/env bash
# Deploy Utsav to Cloud Run (re-runnable). Usage: PROJECT_ID=<id> deploy/cloudrun.sh
# The Gemini key is read from .env and stored in Secret Manager, never in the image.
set -euo pipefail
cd "$(dirname "$0")/.."
PROJECT_ID="${PROJECT_ID:?set PROJECT_ID}"
REGION="${REGION:-asia-south1}"
SERVICE="${SERVICE:-utsav}"
SECRET="utsav-gemini-api-key"

gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com secretmanager.googleapis.com --project "$PROJECT_ID"

KEY="$(sed -n 's/^GEMINI_API_KEY=//p' .env | head -1)"
if ! gcloud secrets describe "$SECRET" --project "$PROJECT_ID" >/dev/null 2>&1; then
  printf '%s' "$KEY" | gcloud secrets create "$SECRET" --data-file=- --project "$PROJECT_ID"
else
  printf '%s' "$KEY" | gcloud secrets versions add "$SECRET" --data-file=- --project "$PROJECT_ID" >/dev/null
fi
NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
gcloud secrets add-iam-policy-binding "$SECRET" --project "$PROJECT_ID" \
  --member "serviceAccount:${NUMBER}-compute@developer.gserviceaccount.com" \
  --role roles/secretmanager.secretAccessor >/dev/null

# One warm instance: SQLite lives in the container, so scaling to zero would wipe data.
# shortcut: data survives idle periods but not redeploys; move to Cloud SQL for production.
gcloud run deploy "$SERVICE" --source . --project "$PROJECT_ID" --region "$REGION" \
  --allow-unauthenticated --min-instances 1 --max-instances 1 \
  --memory 512Mi --cpu 1 --timeout 300 \
  --set-secrets "GEMINI_API_KEY=${SECRET}:latest" --quiet

gcloud run services describe "$SERVICE" --project "$PROJECT_ID" --region "$REGION" \
  --format 'value(status.url)'
