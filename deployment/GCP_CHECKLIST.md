# GCP Deployment Checklist — Robo Reliance Inner Loop

Track infrastructure provisioning, secrets, schema bootstrap, and Cloud Run deployment for the Inner Loop platform.

**Prerequisites:** `gcloud` CLI authenticated, billing enabled, Terraform ≥ 1.5, Docker (for local image builds if not using Cloud Build only).

**Project:** `robo-reliance-ops` | **Region:** `us-central1` | **Environment:** `dev`

---

## Phase A — Configure

- [x] **A1. Choose GCP project and region**
  - `project_id = "robo-reliance-ops"`, `region = "us-central1"`
  - Billing enabled (Free Trial — note: Gemini API costs are not covered by free trial credits).

- [x] **A2. Create Terraform variables file**
  ```bash
  cp deployment/terraform/single-project/terraform.tfvars.example \
     deployment/terraform/single-project/terraform.tfvars
  ```
  Edit `terraform.tfvars`:
  - `project_id` — your GCP project ID
  - `region` — e.g. `us-central1`
  - `environment` — `dev` | `staging` | `prod`
  - `allow_public_orchestrator` — `true` for dev webhooks; `false` for prod (use IAP/API Gateway instead)

- [ ] **A3. (Optional) Remote Terraform state**
  - Create a GCS bucket for state.
  - Uncomment the `backend "gcs"` block in `deployment/terraform/single-project/versions.tf`.
  - Re-run `terraform init`.

---

## Phase B — Provision infrastructure

- [x] **B1. Apply Terraform**
  ```bash
  ./deployment/scripts/bootstrap-infra.sh
  ```
  Or manually:
  ```bash
  cd deployment/terraform/single-project
  terraform init
  terraform plan -out=tfplan
  terraform apply tfplan
  ```

- [x] **B2. Record Terraform outputs**
  ```bash
  cd deployment/terraform/single-project
  terraform output orchestrator_url
  terraform output artifact_registry_repository
  terraform output cloud_sql_connection_name
  terraform output orchestrator_service_account
  ```

  **Expected resources created:**
  - VPC + subnet + Private Service Access + VPC connector
  - Cloud SQL PostgreSQL 15 (private IP)
  - Secret Manager: `inner-loop-database-url-dev`, `inner-loop-google-api-key-dev`
  - Artifact Registry: `inner-loop-images`
  - Cloud Run: `inner-loop-orchestrator`, `inner-loop-mcp-qbo`, `inner-loop-mcp-linkedin`, `inner-loop-ops-web`
  - Service accounts: orchestrator, MCP, CI/CD

  **Note:** `allUsers` public access blocked by org policy `iam.allowedPolicyMemberDomains`. Services require authenticated access via identity token or `gcloud run services proxy`.

---

## Phase C — Secrets & database

- [x] **C1. Set Gemini API key**
  ```bash
  echo -n 'YOUR_GEMINI_API_KEY' | gcloud secrets versions add \
    inner-loop-google-api-key-dev \
    --project=robo-reliance-ops \
    --data-file=-
  ```
  `DATABASE_URL` is auto-populated by Terraform into Secret Manager.

- [x] **C2. Bootstrap PostgreSQL schema**
  Temporarily enable public IP, use Cloud SQL Auth Proxy + psql:
  ```bash
  gcloud sql instances patch inner-loop-pg-dev --project=robo-reliance-ops --assign-ip --quiet
  /opt/homebrew/share/google-cloud-sdk/bin/cloud-sql-proxy \
    "robo-reliance-ops:us-central1:inner-loop-pg-dev" --port=5433 &
  PGPASSWORD=... psql -h 127.0.0.1 -p 5433 -U engine_admin -d roboreliance \
    -f init-scripts/01_init_schema.sql
  psql ... -f init-scripts/02_platform_configs.sql
  psql ... -f init-scripts/03_chat_bindings.sql
  gcloud sql instances patch inner-loop-pg-dev --project=robo-reliance-ops --no-assign-ip --quiet
  ```
  Or use the exact commands from:
  ```bash
  terraform output -raw schema_bootstrap_command
  ```

- [x] **C3. Verify schema**
  - Tables exist: `visits`, `labor_logs`, `financial_ledgers`, `immutable_audit_trail`, `finance_approval_tokens`, `platform_configs`, `channel_ingestion_cursors`, `space_visit_bindings`, `slack_channel_visit_bindings`, `web_chat_sessions`
  - Seed rows in `platform_configs` (finance, quickbooks, linkedin)

---

## Phase D — Build & deploy containers

- [x] **D1. Configure Docker for Artifact Registry**
  ```bash
  gcloud auth configure-docker us-central1-docker.pkg.dev
  ```

- [x] **D2. Build for linux/amd64 and push**
  Build with `--platform linux/amd64` (required when building on Apple Silicon):
  ```bash
  docker build --platform linux/amd64 -t us-central1-docker.pkg.dev/robo-reliance-ops/inner-loop-images/orchestrator:latest -f orchestrator/Dockerfile orchestrator/
  docker build --platform linux/amd64 -t us-central1-docker.pkg.dev/robo-reliance-ops/inner-loop-images/mcp-quickbooks:latest -f mcp-servers/quickbooks/Dockerfile mcp-servers/quickbooks/
  docker build --platform linux/amd64 -t us-central1-docker.pkg.dev/robo-reliance-ops/inner-loop-images/mcp-linkedin:latest -f mcp-servers/linkedin/Dockerfile mcp-servers/linkedin/
  docker build --platform linux/amd64 -t us-central1-docker.pkg.dev/robo-reliance-ops/inner-loop-images/ops-web:latest -f web/Dockerfile web/
  docker push us-central1-docker.pkg.dev/robo-reliance-ops/inner-loop-images/orchestrator:latest
  docker push us-central1-docker.pkg.dev/robo-reliance-ops/inner-loop-images/mcp-quickbooks:latest
  docker push us-central1-docker.pkg.dev/robo-reliance-ops/inner-loop-images/mcp-linkedin:latest
  docker push us-central1-docker.pkg.dev/robo-reliance-ops/inner-loop-images/ops-web:latest
  ```

- [x] **D3. Deploy to Cloud Run**
  ```bash
  gcloud run deploy inner-loop-mcp-qbo --image=us-central1-docker.pkg.dev/robo-reliance-ops/inner-loop-images/mcp-quickbooks:latest --region=us-central1 --project=robo-reliance-ops --quiet
  gcloud run deploy inner-loop-mcp-linkedin --image=us-central1-docker.pkg.dev/robo-reliance-ops/inner-loop-images/mcp-linkedin:latest --region=us-central1 --project=robo-reliance-ops --quiet
  gcloud run deploy inner-loop-orchestrator --image=us-central1-docker.pkg.dev/robo-reliance-ops/inner-loop-images/orchestrator:latest --region=us-central1 --project=robo-reliance-ops --quiet
  gcloud run deploy inner-loop-ops-web --image=us-central1-docker.pkg.dev/robo-reliance-ops/inner-loop-images/ops-web:latest --region=us-central1 --project=robo-reliance-ops --quiet
  ```

---

## Phase E — Verify end-to-end

- [x] **E1. Health checks**
  ```bash
  TOKEN=$(gcloud auth print-identity-token)
  curl -s -H "Authorization: Bearer $TOKEN" "https://inner-loop-orchestrator-611591209386.us-central1.run.app/health" | jq .
  ```
  **Verified responses:**
  - Orchestrator: `{"service":"inner_loop_orchestrator","environment":"dev","database":"connected","agent":"field_tech_support_agent"}`
  - MCP QuickBooks: `{"service":"mcp_quickbooks","status":"ready"}`
  - MCP LinkedIn: `{"service":"mcp_linkedin","status":"ready"}`
  - Ops Web App: HTTP 200

- [ ] **E2. Slack intake webhook**
  ```bash
  TOKEN=$(gcloud auth print-identity-token)
  curl -s -X POST -H "Authorization: Bearer $TOKEN" \
    "https://inner-loop-orchestrator-611591209386.us-central1.run.app/webhooks/slack" \
    -H 'Content-Type: application/json' \
    -d '{
      "slack_channel_id": "C01234567",
      "location_string": "Denver DC Rack 12",
      "metadata_poc": {
        "name": "Alex Kim",
        "phone": "+13035550123",
        "email": "alex@example.com"
      },
      "trigger_signoff_simulation": true,
      "clock_in": "2026-06-28T08:00:00Z",
      "clock_out": "2026-06-28T12:30:00Z",
      "findings": "Replaced actuator belt and recalibrated torque sensors."
    }' | jq .
  ```
  Save `approval_token` from `signoff_receipt`.

- [ ] **E3. Finance approval (HITL)**
  ```bash
  TOKEN=$(gcloud auth print-identity-token)
  curl -s -X POST -H "Authorization: Bearer $TOKEN" \
    "https://inner-loop-orchestrator-611591209386.us-central1.run.app/webhooks/finance" \
    -H 'Content-Type: application/json' \
    -d '{
      "approval_token": "PASTE_TOKEN_HERE",
      "operator_identity": "finance.manager@roboreliance.internal",
      "action": "approve"
    }' | jq .
  ```

- [ ] **E4. Check MCP adapter logs**
  ```bash
  gcloud run services logs read inner-loop-mcp-qbo --region=us-central1 --limit=20
  gcloud run services logs read inner-loop-mcp-linkedin --region=us-central1 --limit=20
  ```
  Look for `INBOUND` and `RECEIPT` log lines.

- [ ] **E5. Confirm audit trail in Cloud SQL**
  - Row in `immutable_audit_trail` for `webhook_finance_approve`
  - Visit `current_state = completed`, ledger `approval_state = approved`

---

## Phase F — Production hardening (later)

- [ ] **F1. Restrict public orchestrator ingress**
  - Set `allow_public_orchestrator = false` in `terraform.tfvars` (already done — org policy blocks allUsers)
  - Put webhooks behind verified secrets, IAP, or API Gateway

- [ ] **F2. Wire external webhooks**
  - Slack Events API → `https://inner-loop-orchestrator-611591209386.us-central1.run.app/webhooks/slack`
  - Google Chat → `https://inner-loop-orchestrator-611591209386.us-central1.run.app/webhooks/google-chat`
  - Finance automation → `https://inner-loop-orchestrator-611591209386.us-central1.run.app/webhooks/finance`

- [ ] **F3. CI/CD trigger**
  - Cloud Build trigger on push to `main` using `deployment/cloudbuild/build-images.yaml`
  - CI/CD SA: `inner-loop-cicd@robo-reliance-ops.iam.gserviceaccount.com`

- [ ] **F4. Monitoring**
  - Cloud Run metrics + log-based alerts on `/health` failures
  - Optional: Cloud Trace (enabled by default on agents-cli Cloud Run deploys)

- [ ] **F5. Multi-environment**
  - Duplicate `terraform.tfvars` per env (`dev`, `staging`, `prod`)
  - Separate Cloud SQL instances or projects per environment

---

## Quick reference

| Item | Local (Docker Compose) | GCP (Cloud Run) |
|------|------------------------|-----------------|
| Orchestrator | `http://localhost:8080` | `https://inner-loop-orchestrator-611591209386.us-central1.run.app` |
| API docs (Swagger) | `http://localhost:8080/docs` | Use `gcloud run services proxy inner-loop-orchestrator --region us-central1` then `http://localhost:8080/docs` |
| Postgres | `localhost:5432` | Cloud SQL `inner-loop-pg-dev` (private IP, use proxy) |
| MCP QuickBooks | `http://localhost:9001` | `https://inner-loop-mcp-qbo-611591209386.us-central1.run.app` |
| MCP LinkedIn | `http://localhost:9002` | `https://inner-loop-mcp-linkedin-611591209386.us-central1.run.app` |
| Ops Web App | `http://localhost:5173` | `https://inner-loop-ops-web-611591209386.us-central1.run.app` |

**Authenticated access:**
```bash
TOKEN=$(gcloud auth print-identity-token)
curl -H "Authorization: Bearer $TOKEN" https://inner-loop-orchestrator-611591209386.us-central1.run.app/health
```

**Local proxy (opens service on localhost without auth):**
```bash
gcloud run services proxy inner-loop-orchestrator --region us-central1 --project robo-reliance-ops
```

---

## UI status

See [docs/UI_STRATEGY.md](../docs/UI_STRATEGY.md) for the full four-surface model.

| Surface | URL | Purpose |
|---------|-----|---------|
| **Ops Web App** | `gcloud run services proxy inner-loop-ops-web` (dev) | Service requests, timekeeping, finance table, embedded Web Chat |
| **New Service Request** | `POST /api/v1/visits` | Primary intake — web form or Slack API call |
| **Web Chat API** | `POST /api/v1/web-chat/message` | NL queries/commands in web app (not channel listening) |
| **Google Chat agent** | `POST /webhooks/google-chat` | Internal visit spaces — RAG, ingest, NL timekeeping |
| **Slack agent** | `POST /webhooks/slack` | Client/external channels — parallel to Google Chat |
| **Finance webhook** | `POST /webhooks/finance` | Programmatic approve/reject gateway |
| **FastAPI Swagger** | `/docs` | API testing |

Register Google Chat: [deployment/docs/GOOGLE_CHAT_SETUP.md](docs/GOOGLE_CHAT_SETUP.md)
