#!/usr/bin/env bash
# Provision Vertex AI Search data store + engine for the Chef client SOP corpus.
#
# IMPORTANT: We use CONTENT_REQUIRED (GCS/BigQuery import), NOT Google Drive
# Workspace connectors. Native Drive data stores cannot be searched with the
# Cloud Run service account Geary uses (403). Path: Drive → GCS → import.
set -euo pipefail

PROJECT="${PROJECT_ID:-robo-reliance-ops}"
DATA_STORE_ID="sop-chef"
ENGINE_ID="sop-chef"
BUCKET="${SOP_CHEF_BUCKET:-gs://robo-reliance-ops-sop-chef}"
# Shared Drive folder for Chef technical docs (manual export / rclone source)
DRIVE_FOLDER_ID="${DRIVE_FOLDER_ID:-1quTosmucf3hb3fjrWCSW2keudcd7Yj5I}"

TOKEN="$(gcloud auth print-access-token)"
BASE="https://discoveryengine.googleapis.com/v1/projects/${PROJECT}/locations/global/collections/default_collection"

echo "Ensuring GCS bucket ${BUCKET}..."
gcloud storage buckets describe "${BUCKET}" --project="${PROJECT}" >/dev/null 2>&1 \
  || gcloud storage buckets create "${BUCKET}" --project="${PROJECT}" --location=us --uniform-bucket-level-access

echo "Creating data store ${DATA_STORE_ID} (idempotent if exists)..."
curl -sS -X POST \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "x-goog-user-project: ${PROJECT}" \
  -H "Content-Type: application/json" \
  "${BASE}/dataStores?dataStoreId=${DATA_STORE_ID}" \
  -d "{
    \"displayName\": \"SOP — Chef\",
    \"industryVertical\": \"GENERIC\",
    \"solutionTypes\": [\"SOLUTION_TYPE_SEARCH\"],
    \"contentConfig\": \"CONTENT_REQUIRED\"
  }" | python3 -m json.tool || true

echo
echo "Creating engine ${ENGINE_ID} (idempotent if exists)..."
curl -sS -X POST \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "x-goog-user-project: ${PROJECT}" \
  -H "Content-Type: application/json" \
  "${BASE}/engines?engineId=${ENGINE_ID}" \
  -d "{
    \"displayName\": \"SOP Chef Search\",
    \"solutionType\": \"SOLUTION_TYPE_SEARCH\",
    \"dataStoreIds\": [\"${DATA_STORE_ID}\"],
    \"searchEngineConfig\": {
      \"searchTier\": \"SEARCH_TIER_STANDARD\",
      \"searchAddOns\": [\"SEARCH_ADD_ON_LLM\"]
    }
  }" | python3 -m json.tool || true

echo
cat <<EOF
Done. Load Chef docs via Cloud Storage (not Google Drive connector):

  Why: Import documents only lists BigQuery / Cloud Storage for CONTENT_REQUIRED
  stores. Native Drive connectors need GOOGLE_WORKSPACE stores, which Geary
  cannot search with its Cloud Run service account.

  1. Copy files from Drive folder ${DRIVE_FOLDER_ID} into ${BUCKET}/
       https://drive.google.com/drive/folders/${DRIVE_FOLDER_ID}
     Options:
       - Download ZIP from Drive → unzip → gcloud storage cp -r ./chef-docs/* ${BUCKET}/
       - Or rclone: rclone copy gdrive:ChefFolder ${BUCKET#gs://}/ --drive-shared-with-me

  2. In the Console screen you're on: Select → Cloud Storage
     Folder: ${BUCKET}/**
     (or Import with API below)

  3. API import:
     curl -X POST -H "Authorization: Bearer \$(gcloud auth print-access-token)" \\
       -H "x-goog-user-project: ${PROJECT}" -H "Content-Type: application/json" \\
       "${BASE}/dataStores/${DATA_STORE_ID}/branches/default_branch/documents:import" \\
       -d '{"gcsSource":{"inputUris":["${BUCKET}/**"],"dataSchema":"content"},"reconciliationMode":"INCREMENTAL"}'

  4. Smoke-test engines/${ENGINE_ID}/servingConfigs/default_search:search
EOF
