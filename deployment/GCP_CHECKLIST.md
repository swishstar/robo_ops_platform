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

- [x] **E2. Visit lifecycle (create → clock-in → sign-off → approve)**
  Verified via GCP tunnel (`gcloud run services proxy` → `localhost:8080`):
  - `POST /api/v1/visits` — created visit `abc38347`, state `initiated`
  - `POST /api/v1/visits/{id}/clock-in` — state → `active`
  - `POST /api/v1/visits/{id}/signoff` — 4.5 hrs calculated, $675 invoice / $337.50 payout, state → `pending_approval`
  - `POST /api/v1/finance/approve` — state → `completed`, MCP receipts generated (QBO invoice, QBO payout, LinkedIn post staged)

- [x] **E3. Finance approval (HITL)**
  Approval token consumed successfully. Ledger `approval_state = approved`, visit `current_state = completed`.

- [x] **E4. MCP adapter execution**
  Both MCP services invoked during finance approval (step E2):
  - QuickBooks: `create_invoice` + `record_payout` — receipts returned
  - LinkedIn: `stage_post` — completion post staged

- [x] **E5. Audit trail confirmed**
  Visit shows `current_state = completed`, ledger shows `approval_state = approved` in Cloud SQL. Audit trail rows written for each step.

---

## Phase F — Roles & IAM

The platform has two IAM layers: **GCP IAM** (who can reach each Cloud Run service) and **application roles** (what an authenticated user can do inside the orchestrator). Both must be configured before wiring external webhooks.

### Current state (provisioned by Terraform)

| GCP Service Account | Email | GCP IAM Roles |
|---|---|---|
| **Orchestrator** | `inner-loop-orchestrator@robo-reliance-ops.iam.gserviceaccount.com` | `cloudsql.client`, `secretmanager.secretAccessor`, `run.invoker`, `logging.logWriter` |
| **MCP Adapters** | `inner-loop-mcp@robo-reliance-ops.iam.gserviceaccount.com` | `logging.logWriter` |
| **CI/CD Runner** | `inner-loop-cicd@robo-reliance-ops.iam.gserviceaccount.com` | `run.admin`, `artifactregistry.writer`, `iam.serviceAccountUser` (can impersonate orchestrator + MCP SAs) |

**Service-to-service auth** (already enforced):
- Orchestrator SA can invoke MCP QuickBooks and MCP LinkedIn Cloud Run services (`roles/run.invoker` bound per-service in `cloud_run.tf`)
- No other identity can invoke the MCP services (they are not public)

**Application-level roles** (enforced in `orchestrator/auth.py`):

| App Role | Permissions | How resolved |
|---|---|---|
| `technician` | Create visits, clock in/out, sign off, view own visits, use Web Chat | Default role for all authenticated users |
| `finance_manager` | All technician permissions + view/approve/reject finance ledgers | Matched by email list in `FINANCE_MANAGER_EMAILS` env var |
| `admin` | All permissions (superset of finance_manager) | Explicit `X-User-Role: admin` header (dev) or future IAP claim mapping |

---

### F1. GCP IAM — human access to Cloud Run services

- [x] **F1a. Grant domain users Cloud Run invoker access**
  Applied for `roboreliance.com` and `user:steve.wishstar@roboreliance.com` on both `inner-loop-orchestrator` and `inner-loop-ops-web`.

- [x] **F1b. Add Terraform resource for domain/group invoker binding**
  Added `authorized_domain`, `authorized_invoker_members`, and IAM member resources in `cloud_run.tf` / `variables.tf`. Applied via Terraform (synced with live bindings).

---

### F2. Application roles — production auth

- [x] **F2a. Implement IAP JWT validation in `auth.py`**
  Real signature verification via `google.oauth2.id_token.verify_token` + IAP certs URL. Audience checked when `IAP_AUDIENCE` is set. Redeployed to Cloud Run.

- [x] **F2b. Configure finance manager email list**
  Cloud Run env vars set (also managed by Terraform):
  - `FINANCE_MANAGER_EMAILS=finance@roboreliance.com,steve.wishstar@roboreliance.com`
  - `ADMIN_EMAILS=steve.wishstar@roboreliance.com`

- [ ] **F2c. (Optional) Map roles from Google Groups instead of email lists**
  Deferred — email lists are sufficient for current scale.

- [x] **F2d. Lock down dev-mode auth in production**
  Outside `ENVIRONMENT=development`, `X-User-Role` is ignored. Roles resolve only from `ADMIN_EMAILS` / `FINANCE_MANAGER_EMAILS`. Verified: finance endpoint succeeds for Steve even when caller sends `X-User-Role: technician`.

---

### F3. Webhook caller identity

- [ ] **F3a. Slack webhook verification**
  Validate the `X-Slack-Signature` header on every `/webhooks/slack` request:
  1. Add `SLACK_SIGNING_SECRET` to Secret Manager
  2. Add it as a secret env var on the orchestrator Cloud Run service
  3. Implement HMAC-SHA256 signature verification in the webhook handler
  See: [Slack — Verifying requests](https://api.slack.com/authentication/verifying-requests-from-slack)
  *Blocked on Slack app creation (Phase G2a).*

- [ ] **F3b. Google Chat JWT verification**
  Verify the `Authorization: Bearer` JWT on `/webhooks/google-chat`:
  - Validate `iss = "chat@system.gserviceaccount.com"`
  - Validate `aud = PROJECT_NUMBER` (611591209386)
  - Verify signature against Google's public keys
  See: [Google Chat — Authenticate](https://developers.google.com/workspace/chat/authenticate-authorize)
  *Blocked on Google Chat app registration (Phase G2b).*

- [x] **F3c. Finance webhook — require identity token**
  Already enforced by Cloud Run IAM (no public invoker). Callers must present a GCP identity token. Approval tokens remain single-use / TTL-limited.

---

### F4. Audit & least privilege review

- [x] **F4a. Verify least privilege for service accounts**
  Confirmed 2026-07-13:
  - orchestrator: `cloudsql.client`, `secretmanager.secretAccessor`, `run.invoker`, `logging.logWriter`
  - mcp: `logging.logWriter`
  - cicd: `run.admin`, `artifactregistry.writer`, `iam.serviceAccountUser`

- [ ] **F4b. Enable Cloud Audit Logs for sensitive APIs**
  ```bash
  # Admin Activity logs are enabled by default.
  # Enable Data Access logs for Secret Manager and Cloud SQL:
  gcloud projects get-iam-policy robo-reliance-ops --format=json > /tmp/policy.json
  # Edit to add auditConfigs for secretmanager.googleapis.com and sqladmin.googleapis.com
  # then: gcloud projects set-iam-policy robo-reliance-ops /tmp/policy.json
  ```

- [x] **F4c. Review SA key policy**
  Confirmed: no user-managed keys on orchestrator, MCP, or CI/CD service accounts.

---

## Phase G — Production hardening

### G1. Ingress & authentication

- [ ] **G1a. Confirm orchestrator ingress is restricted**
  Already enforced — org policy `iam.allowedPolicyMemberDomains` blocks `allUsers`.
  `allow_public_orchestrator = false` in `terraform.tfvars`.

- [ ] **G1b. Set up Identity-Aware Proxy (IAP) for the Ops Web App**
  Provides domain-scoped Google login for browser access (no proxy needed):
  ```bash
  # Enable IAP API
  gcloud services enable iap.googleapis.com --project=robo-reliance-ops

  # Configure OAuth consent screen in Console:
  # https://console.cloud.google.com/apis/credentials/consent?project=robo-reliance-ops
  # - Internal app type (Workspace domain only)
  # - App name: "Robo Reliance Ops"

  # Create OAuth client credentials, then configure IAP for the Cloud Run service
  # via Console: https://console.cloud.google.com/security/iap?project=robo-reliance-ops
  ```
  Alternatively, keep using `gcloud run services proxy` for dev access.

- [ ] **G1c. Secure webhook endpoints with verification secrets**
  Detailed steps in Phase F3 above — Slack signature, Google Chat JWT, finance identity token.

---

### G2. Wire external webhooks

- [ ] **G2a. Register Slack app**
  1. Create a Slack app at [api.slack.com/apps](https://api.slack.com/apps)
  2. Enable Event Subscriptions:
     - **Request URL:** `https://inner-loop-orchestrator-611591209386.us-central1.run.app/webhooks/slack`
     - Subscribe to: `message.channels`, `app_mention`
  3. Add the signing secret to Secret Manager:
     ```bash
     echo -n 'YOUR_SLACK_SIGNING_SECRET' | gcloud secrets create inner-loop-slack-signing-secret-dev \
       --project=robo-reliance-ops --data-file=-
     ```
  4. Install the app to your Slack workspace

- [ ] **G2b. Register Google Chat app**
  Follow [deployment/docs/GOOGLE_CHAT_SETUP.md](docs/GOOGLE_CHAT_SETUP.md):
  1. Open [Chat API Configuration](https://console.cloud.google.com/apis/api/chat.googleapis.com/hangouts-chat?project=robo-reliance-ops)
  2. Create app "Robo Reliance Field Agent"
  3. HTTP endpoint: `https://inner-loop-orchestrator-611591209386.us-central1.run.app/webhooks/google-chat`
  4. Enable 1:1 messages and space conversations
  5. Set visibility to domain-only

- [ ] **G2c. Finance webhook integration**
  For programmatic finance approval (e.g. from an approval workflow or admin tool):
  ```bash
  TOKEN=$(gcloud auth print-identity-token --audiences=https://inner-loop-orchestrator-611591209386.us-central1.run.app)
  curl -X POST -H "Authorization: Bearer $TOKEN" \
    "https://inner-loop-orchestrator-611591209386.us-central1.run.app/webhooks/finance" \
    -H 'Content-Type: application/json' \
    -d '{"approval_token": "...", "operator_identity": "...", "action": "approve"}'
  ```

---

### G3. CI/CD pipeline

The Cloud Build config and CI/CD service account are already provisioned by Terraform.

- [ ] **G3a. Connect GitHub repo to Cloud Build**
  ```bash
  # In Console: https://console.cloud.google.com/cloud-build/triggers?project=robo-reliance-ops
  # 1. Connect Repository → GitHub → select robo-ai-architecture repo
  # 2. Create Trigger:
  #    - Name: deploy-on-push-to-main
  #    - Event: Push to branch
  #    - Branch: ^main$
  #    - Cloud Build config: deployment/cloudbuild/build-images.yaml
  #    - Service account: inner-loop-cicd@robo-reliance-ops.iam.gserviceaccount.com
  ```

- [ ] **G3b. Verify CI/CD service account permissions**
  Already provisioned by Terraform (`iam.tf`):
  - `roles/run.admin` — deploy to Cloud Run
  - `roles/artifactregistry.writer` — push images
  - `roles/iam.serviceAccountUser` — impersonate orchestrator + MCP SAs during deploy

  Verify:
  ```bash
  gcloud projects get-iam-policy robo-reliance-ops \
    --flatten="bindings[].members" \
    --filter="bindings.members:inner-loop-cicd@robo-reliance-ops.iam.gserviceaccount.com" \
    --format="table(bindings.role)"
  ```

- [ ] **G3c. Test a manual Cloud Build run**
  ```bash
  gcloud builds submit . \
    --config=deployment/cloudbuild/build-images.yaml \
    --project=robo-reliance-ops \
    --substitutions=SHORT_SHA=$(git rev-parse --short HEAD)
  ```
  Build pipeline: build 4 images → push to Artifact Registry → deploy all 4 to Cloud Run.

---

### G4. Monitoring & alerting

- [ ] **G4a. Cloud Run health check alerts**
  Create a log-based alert for orchestrator startup failures or unhealthy responses:
  ```bash
  gcloud logging metrics create orchestrator-errors \
    --project=robo-reliance-ops \
    --description="Cloud Run orchestrator error logs" \
    --log-filter='resource.type="cloud_run_revision" AND resource.labels.service_name="inner-loop-orchestrator" AND severity>=ERROR'
  ```
  Then create an alerting policy in Console or via `gcloud alpha monitoring policies create`.

- [ ] **G4b. Uptime checks**
  ```bash
  # Console: https://console.cloud.google.com/monitoring/uptime?project=robo-reliance-ops
  # Create an HTTPS uptime check:
  #   - URL: https://inner-loop-orchestrator-611591209386.us-central1.run.app/health
  #   - Check interval: 5 minutes
  #   - Auth: Service account identity token
  #   - Alert on failure
  ```

- [ ] **G4c. Cloud Trace**
  Enabled by default on Cloud Run. View traces at:
  `https://console.cloud.google.com/traces?project=robo-reliance-ops`

- [ ] **G4d. Dashboard**
  Create a Cloud Monitoring dashboard with:
  - Cloud Run request count, latency (p50/p95/p99), error rate for all 4 services
  - Cloud SQL connections, CPU, memory, disk usage
  - MCP adapter response times

---

### G5. RAG grounding (Vertex AI Search)

The `lookup_technical_sop` tool currently returns stub data. To enable real RAG:

- [ ] **G5a. Create a Vertex AI Search data store**
  ```bash
  # Enable Discovery Engine API
  gcloud services enable discoveryengine.googleapis.com --project=robo-reliance-ops

  # Create data store in Console:
  # https://console.cloud.google.com/gen-app-builder/data-stores?project=robo-reliance-ops
  # - Data store type: Unstructured documents
  # - Source: Google Drive folder /03_Technical_Library
  # - Name: sop-library
  ```

- [ ] **G5b. Create a search engine/app**
  ```bash
  # Console: https://console.cloud.google.com/gen-app-builder/engines?project=robo-reliance-ops
  # - Engine type: Search
  # - Attach data store: sop-library
  # - Name: sop-library-search
  ```

- [ ] **G5c. Wire the tool to the real endpoint**
  Update `orchestrator/agent_def.py` `lookup_technical_sop` to call the Vertex AI Search API in production, using the search engine's serving config endpoint.

- [ ] **G5d. (Optional) Field learnings corpus**
  Create a second data store for field learnings captured from completed visits. Feed `extracted_findings` from `labor_logs` into this corpus to enable cross-visit knowledge retrieval.

---

### G6. Multi-environment

- [ ] **G6a. Create staging environment**
  ```bash
  cp deployment/terraform/single-project/terraform.tfvars \
     deployment/terraform/single-project/terraform.tfvars.staging
  ```
  Edit: `environment = "staging"`, optionally use a separate project ID.

- [ ] **G6b. Use Terraform workspaces or separate state**
  ```bash
  cd deployment/terraform/single-project
  terraform workspace new staging
  terraform plan -var-file=terraform.tfvars.staging -out=tfplan
  terraform apply tfplan
  ```
  Or use separate GCS state buckets per environment (see A3).

- [ ] **G6c. Production environment**
  For production, use a **separate GCP project** (`robo-reliance-prod`) with:
  - Stricter IAM (no public access, IAP-only)
  - Higher Cloud Run scaling limits
  - Cloud SQL HA (regional, failover replica)
  - Cloud Build trigger on release tags instead of `main` pushes

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
