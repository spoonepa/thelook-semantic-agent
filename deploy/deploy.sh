#!/usr/bin/env bash
# Build, push, and deploy the agent + eval job via Cloud Build.
# Usage: ./deploy/deploy.sh
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
repo_root="$(cd "$here/.." && pwd)"

if [ ! -f "$here/.env" ]; then
  echo "Missing $here/.env — copy from .env.example and fill it in."
  exit 1
fi
# shellcheck disable=SC1091
source "$here/.env"

: "${GCP_PROJECT:?}"
: "${GCP_REGION:?}"
: "${ARTIFACT_REPO:?}"
: "${SERVICE_NAME:?}"
: "${EVAL_JOB_NAME:?}"
: "${SERVICE_ACCOUNT:?}"
: "${DBT_SL_HOST:?}"
: "${DBT_SL_ENV_ID:?set DBT_SL_ENV_ID in deploy/.env}"
: "${AGENT_MODEL:?}"
: "${EVAL_BUCKET:?}"

cd "$repo_root"

echo "==> Submitting Cloud Build"
gcloud builds submit \
  --project="$GCP_PROJECT" \
  --config=cloudbuild.yaml \
  --substitutions="_REGION=${GCP_REGION},_REPO=${ARTIFACT_REPO},_SERVICE=${SERVICE_NAME},_JOB=${EVAL_JOB_NAME},_SA=${SERVICE_ACCOUNT},_DBT_SL_HOST=${DBT_SL_HOST},_DBT_SL_ENV_ID=${DBT_SL_ENV_ID},_AGENT_MODEL=${AGENT_MODEL},_EVAL_BUCKET=${EVAL_BUCKET}" \
  .

URL="$(gcloud run services describe "$SERVICE_NAME" \
  --region="$GCP_REGION" --project="$GCP_PROJECT" \
  --format='value(status.url)')"

cat <<EOF

==> Deployed.
Service URL: $URL

Smoke test (requires roles/run.invoker on the service):
  TOKEN=\$(gcloud auth print-identity-token)
  curl -H "Authorization: Bearer \$TOKEN" \\
       -H 'Content-Type: application/json' \\
       -d '{"question":"what was revenue last month?"}' \\
       "$URL/ask"

Run the eval job manually:
  gcloud run jobs execute $EVAL_JOB_NAME --region=$GCP_REGION --project=$GCP_PROJECT --wait

Results land in: gs://$EVAL_BUCKET/runs/
EOF
