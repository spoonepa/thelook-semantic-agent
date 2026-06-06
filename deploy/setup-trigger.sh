#!/usr/bin/env bash
# Create a Cloud Build trigger that fires on push to the configured branch
# of the GitHub repo and runs cloudbuild.yaml.
#
# Prerequisites:
#   1. ./deploy/bootstrap.sh has been run (creates the Cloud Build SA).
#   2. This repo is pushed to GitHub.
#   3. The Cloud Build GitHub App is installed and authorized on the repo
#      via Cloud Console -> Cloud Build -> Triggers -> Connect Repository.
#      This is a one-time, console-only OAuth flow.
#
# Usage: ./deploy/setup-trigger.sh
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
if [ ! -f "$here/.env" ]; then
  echo "Missing $here/.env — copy from .env.example and fill it in."
  exit 1
fi
# shellcheck disable=SC1091
source "$here/.env"

: "${GCP_PROJECT:?}"
: "${GCP_REGION:?}"
: "${GITHUB_OWNER:?set GITHUB_OWNER in deploy/.env}"
: "${GITHUB_REPO:?set GITHUB_REPO in deploy/.env}"
: "${ARTIFACT_REPO:?}"
: "${SERVICE_NAME:?}"
: "${EVAL_JOB_NAME:?}"
: "${SERVICE_ACCOUNT:?}"
: "${DBT_SL_HOST:?}"
: "${DBT_SL_ENV_ID:?set DBT_SL_ENV_ID in deploy/.env}"
: "${AGENT_MODEL:?}"
: "${EVAL_BUCKET:?}"
: "${CLOUDBUILD_SA:=cloudbuild-runtime-sa}"
: "${TRIGGER_NAME:=thelook-agent-main}"
: "${TRIGGER_BRANCH:=^main$}"

CB_SA_EMAIL="${CLOUDBUILD_SA}@${GCP_PROJECT}.iam.gserviceaccount.com"

SUBS="_REGION=${GCP_REGION}"
SUBS="${SUBS},_REPO=${ARTIFACT_REPO}"
SUBS="${SUBS},_SERVICE=${SERVICE_NAME}"
SUBS="${SUBS},_JOB=${EVAL_JOB_NAME}"
SUBS="${SUBS},_SA=${SERVICE_ACCOUNT}"
SUBS="${SUBS},_DBT_SL_HOST=${DBT_SL_HOST}"
SUBS="${SUBS},_DBT_SL_ENV_ID=${DBT_SL_ENV_ID}"
SUBS="${SUBS},_AGENT_MODEL=${AGENT_MODEL}"
SUBS="${SUBS},_EVAL_BUCKET=${EVAL_BUCKET}"

# Only rebuild when files that affect the agent image change. dbt model edits
# don't need a new container.
INCLUDED="agent/**,eval/**,Dockerfile,cloudbuild.yaml"

if gcloud builds triggers describe "$TRIGGER_NAME" --project="$GCP_PROJECT" >/dev/null 2>&1; then
  cat <<EOF
Trigger '$TRIGGER_NAME' already exists. To replace it:
  gcloud builds triggers delete $TRIGGER_NAME --project=$GCP_PROJECT
Then re-run this script.
EOF
  exit 1
fi

echo "==> Creating trigger '$TRIGGER_NAME'"
gcloud builds triggers create github \
  --project="$GCP_PROJECT" \
  --name="$TRIGGER_NAME" \
  --description="Build + deploy thelook agent on push to $TRIGGER_BRANCH" \
  --repo-owner="$GITHUB_OWNER" \
  --repo-name="$GITHUB_REPO" \
  --branch-pattern="$TRIGGER_BRANCH" \
  --build-config=cloudbuild.yaml \
  --included-files="$INCLUDED" \
  --service-account="projects/${GCP_PROJECT}/serviceAccounts/${CB_SA_EMAIL}" \
  --substitutions="$SUBS"

cat <<EOF

==> Trigger created.
Next push to '$TRIGGER_BRANCH' on $GITHUB_OWNER/$GITHUB_REPO will build, push,
and deploy. Watch runs at:
  https://console.cloud.google.com/cloud-build/builds?project=$GCP_PROJECT

To fire it manually without a push:
  gcloud builds triggers run $TRIGGER_NAME --branch=main --project=$GCP_PROJECT
EOF
