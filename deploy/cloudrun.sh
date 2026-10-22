#!/usr/bin/env bash
# Deploy Utsav to Cloud Run (re-runnable). Usage: PROJECT_ID=<id> deploy/cloudrun.sh
# Secrets (Gemini key, optional WhatsApp credentials) are read from .env into Secret
# Manager, never baked into the image. Data lives in Firestore, so instances are stateless.
set -euo pipefail
cd "$(dirname "$0")/.."
PROJECT_ID="${PROJECT_ID:?set PROJECT_ID}"
REGION="${REGION:-asia-south1}"
SERVICE="${SERVICE:-utsav}"
SECRET="utsav-gemini-api-key"

gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com secretmanager.googleapis.com firestore.googleapis.com \
  --project "$PROJECT_ID"

if ! gcloud firestore databases describe --database='(default)' --project "$PROJECT_ID" >/dev/null 2>&1; then
  gcloud firestore databases create --location "$REGION" --type firestore-native --project "$PROJECT_ID"
fi

NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
RUNTIME_SA="${NUMBER}-compute@developer.gserviceaccount.com"
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member "serviceAccount:${RUNTIME_SA}" \
  --role roles/datastore.user --condition=None >/dev/null

# Each non-empty .env value below becomes a Secret Manager secret mounted as that env var.
SECRETS=()
for VAR in GEMINI_API_KEY WHATSAPP_TOKEN WHATSAPP_PHONE_NUMBER_ID WHATSAPP_APP_SECRET WHATSAPP_VERIFY_TOKEN; do
  VALUE="$(sed -n "s/^${VAR}=//p" .env | head -1)"
  [ -z "$VALUE" ] && continue
  NAME="$([ "$VAR" = GEMINI_API_KEY ] && echo "$SECRET" || echo "utsav-$(echo "$VAR" | tr 'A-Z_' 'a-z-')")"
  if ! gcloud secrets describe "$NAME" --project "$PROJECT_ID" >/dev/null 2>&1; then
    printf '%s' "$VALUE" | gcloud secrets create "$NAME" --data-file=- --project "$PROJECT_ID"
  else
    printf '%s' "$VALUE" | gcloud secrets versions add "$NAME" --data-file=- --project "$PROJECT_ID" >/dev/null
  fi
  gcloud secrets add-iam-policy-binding "$NAME" --project "$PROJECT_ID" \
    --member "serviceAccount:${RUNTIME_SA}" --role roles/secretmanager.secretAccessor >/dev/null
  SECRETS+=("${VAR}=${NAME}:latest")
done

# shortcut: login and AI quotas are per instance, so the effective limit is up to 3x;
# move them to Firestore or Redis before raising max-instances further.
gcloud run deploy "$SERVICE" --source . --project "$PROJECT_ID" --region "$REGION" \
  --allow-unauthenticated --min-instances 0 --max-instances 3 \
  --memory 512Mi --cpu 1 --timeout 300 \
  --set-env-vars "UTSAV_STORE=firestore" \
  --set-secrets "$(IFS=,; echo "${SECRETS[*]}")" --quiet

gcloud run services describe "$SERVICE" --project "$PROJECT_ID" --region "$REGION" \
  --format 'value(status.url)'
