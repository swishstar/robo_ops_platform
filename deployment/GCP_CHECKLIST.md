# GCP Deployment Checklist — Robo Reliance Inner Loop

Track infrastructure provisioning, secrets, schema bootstrap, and Cloud Run deployment for the Inner Loop platform.

**Prerequisites:** `gcloud` CLI authenticated, billing enabled, Terraform ≥ 1.5, Docker (for local image builds if not using Cloud Build only).

---

## Phase A — Configure

- [ ] **A1. Choose GCP project and region**
  - Example: `project_id = "robo-reliance-dev"`, `region = "us-central1"`
  - Enable billing on the project.

- [ ] **A2. Create Terraform variables file**
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

- [ ] **B1. Apply Terraform**
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

- [ ] **B2. Record Terraform outputs**
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
  - Secret Manager: `inner-loop-database-url-{env}`, `inner-loop-google-api-key-{env}`
  - Artifact Registry: `inner-loop-images`
  - Cloud Run: `inner-loop-orchestrator`, `inner-loop-mcp-qbo`, `inner-loop-mcp-linkedin`
  - Service accounts: orchestrator, MCP, CI/CD

---

## Phase C — Secrets & database

- [ ] **C1. Set Gemini API key**
  ```bash
  # Replace secret name if environment != dev
  echo -n 'YOUR_GEMINI_API_KEY' | gcloud secrets versions add \
    inner-loop-google-api-key-dev \
    --project=YOUR_GCP_PROJECT_ID \
    --data-file=-
  ```
  `DATABASE_URL` is auto-populated by Terraform into Secret Manager.

- [ ] **C2. Bootstrap PostgreSQL schema**
  From repo root (requires Cloud SQL Auth / authorized network or Cloud SQL Proxy):
  ```bash
  gcloud sql connect inner-loop-pg-dev \
    --project=YOUR_GCP_PROJECT_ID \
    --user=engine_admin \
    --database=roboreliance < init-scripts/01_init_schema.sql

  gcloud sql connect inner-loop-pg-dev \
    --project=YOUR_GCP_PROJECT_ID \
    --user=engine_admin \
    --database=roboreliance < init-scripts/02_platform_configs.sql
  ```
  Or use the exact commands from:
  ```bash
  terraform output -raw schema_bootstrap_command
  ```

- [ ] **C3. Verify schema**
  - Tables exist: `visits`, `labor_logs`, `financial_ledgers`, `immutable_audit_trail`, `finance_approval_tokens`, `platform_configs`
  - Seed rows in `platform_configs` (finance, quickbooks, linkedin)

---

## Phase D — Build & deploy containers

- [ ] **D1. Configure Docker for Artifact Registry**
  ```bash
  gcloud auth configure-docker us-central1-docker.pkg.dev
  ```

- [ ] **D2. Build and push via Cloud Build (recommended)**
  ```bash
  gcloud builds submit --config deployment/cloudbuild/build-images.yaml .
  ```

- [ ] **D3. Or build locally and push**
  ```bash
  terraform output -raw image_build_commands
  ```
  Run the printed `docker build` / `docker push` commands.

- [ ] **D4. Update Cloud Run with real images (if Terraform used placeholder)**
  After first push, either:
  - Re-apply Terraform with image URIs in `terraform.tfvars`:
    ```hcl
    orchestrator_image   = "us-central1-docker.pkg.dev/PROJECT/inner-loop-images/orchestrator:latest"
    mcp_quickbooks_image = "us-central1-docker.pkg.dev/PROJECT/inner-loop-images/mcp-quickbooks:latest"
    mcp_linkedin_image   = "us-central1-docker.pkg.dev/PROJECT/inner-loop-images/mcp-linkedin:latest"
    ```
  - Or rely on Cloud Build deploy steps in `build-images.yaml`.

- [ ] **D5. (Alternative) agents-cli deploy**
  After infra exists:
  ```bash
  agents-cli deploy --project YOUR_GCP_PROJECT_ID --region us-central1
  ```

---

## Phase E — Verify end-to-end

- [ ] **E1. Health checks**
  ```bash
  ORCH_URL=$(terraform output -raw orchestrator_url)
  curl -s "$ORCH_URL/health" | jq .
  curl -s "$ORCH_URL/agent/metadata" | jq .
  ```

- [ ] **E2. Slack intake webhook**
  ```bash
  curl -s -X POST "$ORCH_URL/webhooks/slack" \
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
  curl -s -X POST "$ORCH_URL/webhooks/finance" \
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
  - Set `allow_public_orchestrator = false` in `terraform.tfvars`
  - Put webhooks behind verified secrets, IAP, or API Gateway

- [ ] **F2. Wire external webhooks**
  - Slack Events API → `https://<orchestrator-url>/webhooks/slack`
  - Google Chat → `https://<orchestrator-url>/webhooks/google-chat`
  - Finance automation → `https://<orchestrator-url>/webhooks/finance`

- [ ] **F3. CI/CD trigger**
  - Cloud Build trigger on push to `main` using `deployment/cloudbuild/build-images.yaml`
  - CI/CD SA: `inner-loop-cicd@PROJECT.iam.gserviceaccount.com`

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
| Orchestrator | `http://localhost:8080` | `terraform output orchestrator_url` |
| API docs (Swagger) | `http://localhost:8080/docs` | `<orchestrator-url>/docs` |
| Postgres | `localhost:5432` | Cloud SQL (private) |
| MCP QuickBooks | `http://localhost:9001` | IAM-only Cloud Run service |
| MCP LinkedIn | `http://localhost:9002` | IAM-only Cloud Run service |

---

## UI status

See [docs/UI_STRATEGY.md](../docs/UI_STRATEGY.md) for the full three-surface model.

| Surface | URL | Purpose |
|---------|-----|---------|
| **Ops Web App** | `http://localhost:5173` (dev) / `terraform output ops_web_url` | Service requests, timekeeping, finance table, embedded Web Chat |
| **New Service Request** | `POST /api/v1/visits` | Primary intake — web form or Slack API call |
| **Web Chat API** | `POST /api/v1/web-chat/message` | NL queries/commands in web app (not channel listening) |
| **Google Chat agent** | `POST /webhooks/google-chat` | Internal visit spaces — RAG, ingest, NL timekeeping |
| **Slack agent** | `POST /webhooks/slack` | Client/external channels — parallel to Google Chat |
| **Finance webhook** | `POST /webhooks/finance` | Programmatic approve/reject gateway |
| **FastAPI Swagger** | `/docs` | API testing |

Register Google Chat: [deployment/docs/GOOGLE_CHAT_SETUP.md](docs/GOOGLE_CHAT_SETUP.md)
