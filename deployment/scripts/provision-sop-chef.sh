#!/usr/bin/env bash
# Provision Vertex AI Search data store + engine for the Chef client SOP corpus,
# then print Console steps to attach the Shared Drive folder.
set -euo pipefail

PROJECT="${PROJECT_ID:-robo-reliance-ops}"
DATA_STORE_ID="sop-chef"
ENGINE_ID="sop-chef"
# Shared Drive folder for Chef technical docs
DRIVE_FOLDER_ID="${DRIVE_FOLDER_ID:-1quTosmucf3hb3fjrWCSW2keudcd7Yj5I}"

TOKEN="$(gcloud auth print-access-token)"
BASE="https://discoveryengine.googleapis.com/v1/projects/${PROJECT}/locations/global/collections/default_collection"

echo "Creating data store ${DATA_STORE_ID}..."
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
  }" | python3 -m json.tool

echo
echo "Creating engine ${ENGINE_ID}..."
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
  }" | python3 -m json.tool

echo
echo "Done. Attach the Chef Shared Drive folder in Console (OAuth required):"
echo "  1. https://console.cloud.google.com/gen-app-builder/data-stores/${DATA_STORE_ID}?project=${PROJECT}"
echo "  2. Add data → Google Drive → folder ID ${DRIVE_FOLDER_ID}"
echo "  3. Share the Shared Drive with the connector Google account (Viewer+)"
echo "  4. Wait for indexing, then smoke-test:"
echo "     query against engines/${ENGINE_ID}/servingConfigs/default_search:search"
