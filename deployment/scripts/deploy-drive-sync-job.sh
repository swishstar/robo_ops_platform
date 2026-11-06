#!/usr/bin/env bash
# Build/push the Drive→GCS sync image and create/update a Cloud Run Job + daily Scheduler.
#
# Shared Drives that block non-@roboreliance.com members cannot share with a GCP SA.
# Drive reads therefore use OAuth as a Workspace user (refresh token in Secret Manager).
# GCS upload + Discovery Engine import still use the sync service account.
set -euo pipefail

PROJECT="${PROJECT_ID:-robo-reliance-ops}"
REGION="${REGION:-us-central1}"
REPO="${ARTIFACT_REPO:-inner-loop-images}"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/drive-sync:latest"
JOB_NAME="${JOB_NAME:-inner-loop-drive-sync-chef}"
SA_EMAIL="${SYNC_SA:-inner-loop-drive-sync@${PROJECT}.iam.gserviceaccount.com}"
FOLDER_ID="${DRIVE_FOLDER_ID:-1quTosmucf3hb3fjrWCSW2keudcd7Yj5I}"
GCS_URI="${GCS_URI:-gs://robo-reliance-ops-sop-chef}"
DATA_STORE_ID="${DATA_STORE_ID:-sop-chef}"
SCHEDULER_NAME="${SCHEDULER_NAME:-inner-loop-drive-sync-chef-daily}"
SECRET_CLIENT_ID="${SECRET_CLIENT_ID:-inner-loop-drive-oauth-client-id}"
SECRET_CLIENT_SECRET="${SECRET_CLIENT_SECRET:-inner-loop-drive-oauth-client-secret}"
SECRET_REFRESH="${SECRET_REFRESH:-inner-loop-drive-oauth-refresh-token}"

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

echo "Ensuring service account ${SA_EMAIL}..."
gcloud iam service-accounts describe "${SA_EMAIL}" --project="${PROJECT}" >/dev/null 2>&1 \
  || gcloud iam service-accounts create inner-loop-drive-sync \
      --project="${PROJECT}" \
      --display-name="Inner Loop Drive→GCS sync"

echo "Granting GCS + Discovery Engine + secretAccessor roles..."
gcloud storage buckets add-iam-policy-binding "${GCS_URI}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/storage.objectAdmin" \
  --project="${PROJECT}" --quiet >/dev/null 2>&1 || true
gcloud projects add-iam-policy-binding "${PROJECT}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/discoveryengine.editor" \
  --condition=None --quiet >/dev/null
gcloud projects add-iam-policy-binding "${PROJECT}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/secretmanager.secretAccessor" \
  --condition=None --quiet >/dev/null

missing=0
for s in "${SECRET_CLIENT_ID}" "${SECRET_CLIENT_SECRET}" "${SECRET_REFRESH}"; do
  if ! gcloud secrets describe "${s}" --project="${PROJECT}" >/dev/null 2>&1; then
    echo "MISSING secret: ${s}"
    missing=1
  fi
done
if [[ "${missing}" -eq 1 ]]; then
  cat <<EOF

Create OAuth Desktop client in Console, then run once as a Drive member:

  cd deployment/drive-sync
  pip install -r requirements.txt
  python obtain_drive_oauth.py --client-secrets=/path/to/client_secret.json

Store the printed values:

  echo -n 'CLIENT_ID'     | gcloud secrets create ${SECRET_CLIENT_ID} --data-file=- --project=${PROJECT}
  echo -n 'CLIENT_SECRET' | gcloud secrets create ${SECRET_CLIENT_SECRET} --data-file=- --project=${PROJECT}
  echo -n 'REFRESH'       | gcloud secrets create ${SECRET_REFRESH} --data-file=- --project=${PROJECT}

(Use \`secrets versions add\` if the secret already exists.)
Then re-run this script.
EOF
  exit 1
fi

echo "Building ${IMAGE}..."
gcloud builds submit "${ROOT}/deployment/drive-sync" \
  --project="${PROJECT}" \
  --tag="${IMAGE}" \
  --quiet

SECRET_FLAGS=(
  "--update-secrets=DRIVE_OAUTH_CLIENT_ID=${SECRET_CLIENT_ID}:latest"
  "--update-secrets=DRIVE_OAUTH_CLIENT_SECRET=${SECRET_CLIENT_SECRET}:latest"
  "--update-secrets=DRIVE_OAUTH_REFRESH_TOKEN=${SECRET_REFRESH}:latest"
)

echo "Creating/updating Cloud Run Job ${JOB_NAME}..."
if gcloud run jobs describe "${JOB_NAME}" --region="${REGION}" --project="${PROJECT}" >/dev/null 2>&1; then
  gcloud run jobs update "${JOB_NAME}" \
    --project="${PROJECT}" \
    --region="${REGION}" \
    --image="${IMAGE}" \
    --service-account="${SA_EMAIL}" \
    --set-env-vars="GOOGLE_CLOUD_PROJECT=${PROJECT},DRIVE_FOLDER_ID=${FOLDER_ID},GCS_URI=${GCS_URI},DATA_STORE_ID=${DATA_STORE_ID}" \
    "${SECRET_FLAGS[@]}" \
    --memory=1Gi \
    --task-timeout=60m \
    --max-retries=1
else
  gcloud run jobs create "${JOB_NAME}" \
    --project="${PROJECT}" \
    --region="${REGION}" \
    --image="${IMAGE}" \
    --service-account="${SA_EMAIL}" \
    --set-env-vars="GOOGLE_CLOUD_PROJECT=${PROJECT},DRIVE_FOLDER_ID=${FOLDER_ID},GCS_URI=${GCS_URI},DATA_STORE_ID=${DATA_STORE_ID}" \
    --set-secrets="DRIVE_OAUTH_CLIENT_ID=${SECRET_CLIENT_ID}:latest,DRIVE_OAUTH_CLIENT_SECRET=${SECRET_CLIENT_SECRET}:latest,DRIVE_OAUTH_REFRESH_TOKEN=${SECRET_REFRESH}:latest" \
    --memory=1Gi \
    --task-timeout=60m \
    --max-retries=1
fi

gcloud run jobs add-iam-policy-binding "${JOB_NAME}" \
  --region="${REGION}" \
  --project="${PROJECT}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/run.invoker" --quiet >/dev/null
gcloud projects add-iam-policy-binding "${PROJECT}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/run.developer" \
  --condition=None --quiet >/dev/null

echo "Creating/updating Cloud Scheduler ${SCHEDULER_NAME} (daily 06:00 America/New_York)..."
JOB_URI="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT}/jobs/${JOB_NAME}:run"
if gcloud scheduler jobs describe "${SCHEDULER_NAME}" --location="${REGION}" --project="${PROJECT}" >/dev/null 2>&1; then
  gcloud scheduler jobs update http "${SCHEDULER_NAME}" \
    --project="${PROJECT}" \
    --location="${REGION}" \
    --schedule="0 6 * * *" \
    --time-zone="America/New_York" \
    --uri="${JOB_URI}" \
    --http-method=POST \
    --oauth-service-account-email="${SA_EMAIL}"
else
  gcloud scheduler jobs create http "${SCHEDULER_NAME}" \
    --project="${PROJECT}" \
    --location="${REGION}" \
    --schedule="0 6 * * *" \
    --time-zone="America/New_York" \
    --uri="${JOB_URI}" \
    --http-method=POST \
    --oauth-service-account-email="${SA_EMAIL}"
fi

cat <<EOF

Deployed with Workspace-user OAuth for Drive (no SA share needed).

Then run once:
  gcloud run jobs execute ${JOB_NAME} --region=${REGION} --project=${PROJECT}

Daily sync: Scheduler ${SCHEDULER_NAME} at 06:00 America/New_York.
EOF
