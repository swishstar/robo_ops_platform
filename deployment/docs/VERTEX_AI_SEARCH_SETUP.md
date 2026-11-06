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

## Multi-client SOP corpora (G5e)

One Geary agent; **per-client data stores**. Visit `client_id` selects the engine.

| Client ID | Data store / engine | Drive source |
|---|---|---|
| `chef` | `sop-chef` | [Shared Drive folder](https://drive.google.com/drive/folders/1quTosmucf3hb3fjrWCSW2keudcd7Yj5I) |
| `roboreliance` | `sop-library` / `sop-library-search` | Shared /03_Technical_Library + GCS seed |

Routing:

1. `visits.client_id` set at intake (web **Client** dropdown)
2. `lookup_technical_sop(query, client_id=…)` → `client_corpus.resolve_sop_endpoint`
3. Endpoints from `CLIENT_SOP_ENDPOINTS` env (Terraform) and/or `platform_configs.client_sop_endpoints`

### Provision Chef store + Drive→GCS sync (no ZIP)

`sop-chef` is a **CONTENT_REQUIRED** store (GCS import). Native Drive connectors are a
different store type and **cannot be searched with Geary’s service account**.

**Team workflow:** add/update files in the [Chef Shared Drive folder](https://drive.google.com/drive/folders/1quTosmucf3hb3fjrWCSW2keudcd7Yj5I) → automated job copies to `gs://robo-reliance-ops-sop-chef/` → Discovery Engine re-import. **No ZIP upload.**

```bash
gcloud auth login   # if needed
./deployment/scripts/provision-sop-chef.sh          # data store + engine + bucket
./deployment/scripts/deploy-drive-sync-job.sh       # Cloud Run Job + daily Scheduler
```

**Shared Drive note:** If the drive blocks non-`@roboreliance.com` members, you
**cannot** share it with a GCP service account. Sync reads Drive via **OAuth as a
Workspace user** who is already a member (e.g. you); GCS/import still use the sync SA.

One-time OAuth setup:

1. Console → APIs & Services → Credentials → Create **OAuth client ID** (Desktop app).
2. Download the client JSON, then as a Drive member:
   ```bash
   cd deployment/drive-sync && pip install -r requirements.txt
   python obtain_drive_oauth.py --client-secrets=/path/to/client_secret.json
   ```
3. Store the three printed values in Secret Manager (`inner-loop-drive-oauth-*`),
   then re-run `./deployment/scripts/deploy-drive-sync-job.sh`.
4. Execute once:
   ```bash
   gcloud run jobs execute inner-loop-drive-sync-chef \
     --region=us-central1 --project=robo-reliance-ops
   ```
5. Wait for indexing; smoke-test `engines/sop-chef/.../default_search:search`.

Apply DB migration on Cloud SQL / local Postgres:

```bash
psql "$DATABASE_URL" -f init-scripts/05_client_corpus.sql
```

### Add another client later

1. Create `sop-<client>` data store + engine (copy `provision-sop-chef.sh`)
2. Attach that client's Drive folder in Console
3. Insert/update `platform_configs.clients` + `client_sop_endpoints` (and Terraform `CLIENT_SOP_ENDPOINTS`)
4. No new agent required

## Field learnings (G5d)

Provisioned 2026-10-08/09:

| Resource | ID |
|---|---|
| Data store | `field-learnings` |
| Search engine/app | `field-learnings` |
| Serving config | `default_search` |
| Corpus bucket | `gs://robo-reliance-ops-field-learnings/` |
| Serving URL | `https://discoveryengine.googleapis.com/v1/projects/robo-reliance-ops/locations/global/collections/default_collection/engines/field-learnings/servingConfigs/default_search` |

Orchestrator env `FIELD_LEARNINGS_SEARCH_ENDPOINT` is already set in Terraform. Orchestrator SA needs `roles/discoveryengine.editor` for live document upserts (in addition to `roles/discoveryengine.user` for search).

### Ingest paths

1. **Chat channels** — Google Chat / Slack handlers call `field_learnings_ingest.ingest_chat_message` (production upserts Discovery Engine documents).
2. **Visit sign-off** — `process_visit_signoff` calls `ingest_labor_finding` with `extracted_findings`.
3. **Batch / seed** — upload Markdown under `gs://robo-reliance-ops-field-learnings/` and import:

```bash
TOKEN=$(gcloud auth print-access-token)
curl -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "x-goog-user-project: robo-reliance-ops" \
  -H "Content-Type: application/json" \
  "https://discoveryengine.googleapis.com/v1/projects/robo-reliance-ops/locations/global/collections/default_collection/dataStores/field-learnings/branches/default_branch/documents:import" \
  -d '{
    "gcsSource": {
      "inputUris": ["gs://robo-reliance-ops-field-learnings/**"],
      "dataSchema": "content"
    },
    "reconciliationMode": "INCREMENTAL"
  }'
```

Sample fixture: `deployment/fixtures/field_learnings/sample_actuator_belt.md` (already imported for smoke test).

### Smoke test search

```bash
TOKEN=$(gcloud auth print-access-token)
curl -sS -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "x-goog-user-project: robo-reliance-ops" \
  -H "Content-Type: application/json" \
  "https://discoveryengine.googleapis.com/v1/projects/robo-reliance-ops/locations/global/collections/default_collection/engines/field-learnings/servingConfigs/default_search:search" \
  -d '{"query":"actuator belt A-17","pageSize":3,"contentSearchSpec":{"snippetSpec":{"returnSnippet":true}}}' \
  | python3 -m json.tool | head -80
```
