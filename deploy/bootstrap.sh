#!/usr/bin/env bash
# One-time GCP setup for the thelook semantic agent.
# Idempotent: re-running it is safe.
#
# Usage: ./deploy/bootstrap.sh
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
if [ ! -f "$here/.env" ]; then
  echo "Missing $here/.env — copy from .env.example and fill it in."
  exit 1
fi
# shellcheck disable=SC1091
source "$here/.env"

: "${GCP_PROJECT:?missing in deploy/.env}"
: "${GCP_REGION:?}"
: "${ARTIFACT_REPO:?}"
: "${SERVICE_ACCOUNT:?}"
: "${BQ_DATASET:?}"
: "${EVAL_BUCKET:?}"
: "${BUDGET_AMOUNT_USD:?}"
: "${CLOUDBUILD_SA:=cloudbuild-runtime-sa}"

gcloud config set project "$GCP_PROJECT"

echo "==> Enabling APIs"
gcloud services enable \
  bigquery.googleapis.com \
  aiplatform.googleapis.com \
  secretmanager.googleapis.com \
  artifactregistry.googleapis.com \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  storage.googleapis.com \
  billingbudgets.googleapis.com

echo "==> Artifact Registry repo"
gcloud artifacts repositories create "$ARTIFACT_REPO" \
  --location="$GCP_REGION" \
  --repository-format=docker \
  --description="thelook agent images" 2>/dev/null \
  || echo "    repo exists"

echo "==> BigQuery dataset"
bq --location=US mk -d --description="dbt marts for thelook_semantic" \
  "$GCP_PROJECT:$BQ_DATASET" 2>/dev/null \
  || echo "    dataset exists"

echo "==> GCS bucket for eval results"
gcloud storage buckets create "gs://$EVAL_BUCKET" \
  --location="$GCP_REGION" \
  --uniform-bucket-level-access 2>/dev/null \
  || echo "    bucket exists"

echo "==> Service account"
gcloud iam service-accounts create "$SERVICE_ACCOUNT" \
  --display-name="thelook agent runtime" 2>/dev/null \
  || echo "    sa exists"

SA_EMAIL="${SERVICE_ACCOUNT}@${GCP_PROJECT}.iam.gserviceaccount.com"

echo "==> IAM roles on $SA_EMAIL"
for role in \
  roles/aiplatform.user \
  roles/secretmanager.secretAccessor \
  roles/bigquery.jobUser \
  roles/bigquery.dataViewer \
  roles/storage.objectAdmin; do
  gcloud projects add-iam-policy-binding "$GCP_PROJECT" \
    --member="serviceAccount:$SA_EMAIL" \
    --role="$role" \
    --condition=None \
    --quiet >/dev/null
done

echo "==> Cloud Build runtime service account"
gcloud iam service-accounts create "$CLOUDBUILD_SA" \
  --display-name="thelook agent CI/CD" 2>/dev/null \
  || echo "    sa exists"

CB_SA_EMAIL="${CLOUDBUILD_SA}@${GCP_PROJECT}.iam.gserviceaccount.com"

echo "==> IAM roles on $CB_SA_EMAIL"
for role in \
  roles/run.admin \
  roles/artifactregistry.writer \
  roles/storage.objectAdmin \
  roles/logging.logWriter \
  roles/secretmanager.secretAccessor; do
  gcloud projects add-iam-policy-binding "$GCP_PROJECT" \
    --member="serviceAccount:$CB_SA_EMAIL" \
    --role="$role" \
    --condition=None \
    --quiet >/dev/null
done

# Cloud Build SA must be able to act-as the runtime SA to deploy Cloud Run
# services and Jobs that run as the runtime SA.
gcloud iam service-accounts add-iam-policy-binding "$SA_EMAIL" \
  --member="serviceAccount:$CB_SA_EMAIL" \
  --role="roles/iam.serviceAccountUser" \
  --quiet >/dev/null

echo "==> DBT_SL_TOKEN secret"
if ! gcloud secrets describe DBT_SL_TOKEN >/dev/null 2>&1; then
  printf "REPLACE_ME" | gcloud secrets create DBT_SL_TOKEN --data-file=-
  echo "    created with placeholder. Populate with:"
  echo "    printf 'dbts_xxx' | gcloud secrets versions add DBT_SL_TOKEN --data-file=-"
else
  echo "    secret exists (don't forget to populate a real value)"
fi

echo "==> Billing budget alert"
BILLING_ACCOUNT="$(gcloud billing projects describe "$GCP_PROJECT" \
  --format='value(billingAccountName)' 2>/dev/null | sed 's|.*/||' || true)"
PROJECT_NUMBER="$(gcloud projects describe "$GCP_PROJECT" --format='value(projectNumber)')"
if [ -z "${BILLING_ACCOUNT:-}" ]; then
  echo "    no billing account linked; skipping"
else
  gcloud billing budgets create \
    --billing-account="$BILLING_ACCOUNT" \
    --display-name="thelook-agent-${BUDGET_AMOUNT_USD}usd" \
    --budget-amount="${BUDGET_AMOUNT_USD}USD" \
    --threshold-rule=percent=0.5 \
    --threshold-rule=percent=0.9 \
    --threshold-rule=percent=1.0 \
    --filter-projects="projects/$PROJECT_NUMBER" 2>/dev/null \
    || echo "    budget may already exist; skipping"
fi

cat <<'NOTE'

==> Bootstrap complete.

Remaining manual steps (cannot be scripted):
  1. dbt Cloud trial: connect this repo, configure BigQuery with the
     SA you just created (or a separate dbt-cloud SA), run `dbt build` in a
     Deployment env, enable the Semantic Layer, mint a service token.
  2. Populate the DBT_SL_TOKEN secret:
       printf 'dbts_xxx' | gcloud secrets versions add DBT_SL_TOKEN --data-file=-
  3. Set DBT_SL_ENV_ID in deploy/.env (numeric env id from dbt Cloud).
  4. BigQuery custom quota — set a daily bytes-processed cap in console:
       IAM & Admin -> Quotas & System Limits -> filter "Query usage per day"
  5. Then run ./deploy/deploy.sh (one-shot deploy from your laptop),
     OR, for GitHub-triggered CI/CD:
       a. Push this repo to GitHub.
       b. Console -> Cloud Build -> Triggers -> Connect Repository ->
          GitHub (Cloud Build GitHub App). Authorize on the repo.
       c. Run ./deploy/setup-trigger.sh
NOTE
