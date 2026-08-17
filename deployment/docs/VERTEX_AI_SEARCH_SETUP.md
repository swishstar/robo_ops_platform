# Vertex AI Search (SOP RAG) Setup

Phase G5 — wire `lookup_technical_sop` to Discovery Engine / Vertex AI Search.

## Provisioned resources (`robo-reliance-ops`)

| Resource | ID |
|---|---|
| Data store | `sop-library` |
| Search engine/app | `sop-library-search` |
| Serving config | `default_search` |
| Sample corpus bucket | `gs://robo-reliance-ops-sop-library/` |
| Serving URL | `https://discoveryengine.googleapis.com/v1/projects/robo-reliance-ops/locations/global/collections/default_collection/engines/sop-library-search/servingConfigs/default_search` |

Orchestrator env (`SOP_SEARCH_ENDPOINT`) and IAM (`roles/discoveryengine.user` on the orchestrator SA) are managed in Terraform.

## Seed / expand the corpus

### Option A — GCS (already bootstrapped)

1. Upload PDFs/Markdown under:
   ```bash
   gcloud storage cp ./your-sop.pdf \
     gs://robo-reliance-ops-sop-library/03_Technical_Library/RR-FieldOps/
   ```
2. Re-import:
   ```bash
   TOKEN=$(gcloud auth print-access-token)
   curl -X POST \
     -H "Authorization: Bearer $TOKEN" \
     -H "x-goog-user-project: robo-reliance-ops" \
     -H "Content-Type: application/json" \
     "https://discoveryengine.googleapis.com/v1/projects/robo-reliance-ops/locations/global/collections/default_collection/dataStores/sop-library/branches/default_branch/documents:import" \
     -d '{
       "gcsSource": {
         "inputUris": ["gs://robo-reliance-ops-sop-library/03_Technical_Library/**"],
         "dataSchema": "content"
       },
       "reconciliationMode": "INCREMENTAL"
     }'
   ```

A sample A-17 SOP lives at `deployment/fixtures/sop/error_code_a17.md` and was imported for smoke testing.

### Option B — Google Drive `/03_Technical_Library` (Console)

1. Open [AI Applications → Data stores](https://console.cloud.google.com/gen-app-builder/data-stores?project=robo-reliance-ops)
2. Open **sop-library** → add a **Google Drive** data source for `/03_Technical_Library`
3. Complete the Drive OAuth consent when prompted
4. Wait for indexing to finish

## Smoke test search

```bash
TOKEN=$(gcloud auth print-access-token)
curl -sS -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "x-goog-user-project: robo-reliance-ops" \
  -H "Content-Type: application/json" \
  "https://discoveryengine.googleapis.com/v1/projects/robo-reliance-ops/locations/global/collections/default_collection/engines/sop-library-search/servingConfigs/default_search:search" \
  -d '{"query":"error code A-17","pageSize":3,"contentSearchSpec":{"snippetSpec":{"returnSnippet":true}}}' \
  | python3 -m json.tool | head -80
```

Then in Google Chat: `@Geary what is error code A-17`

## Field learnings (G5d — optional)

Create a second data store/engine named `field-learnings` when ready. The orchestrator already reads `FIELD_LEARNINGS_SEARCH_ENDPOINT`.
