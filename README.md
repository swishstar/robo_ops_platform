# Robo Reliance Ops Platform

Field operations platform for managing service visits, technician timekeeping, and contractor payouts. Built on Google Cloud Platform with an ADK-powered AI agent for RAG, knowledge capture, and natural-language commands.

**Core constraint:** AI interprets and suggests; deterministic Python tools validate and execute every mutation.

## Architecture at a glance

| Layer | Stack |
|-------|-------|
| **Web app** | React + TypeScript (Vite), TanStack Query, Tailwind |
| **Orchestrator** | FastAPI on Cloud Run, Google ADK agent (Gemini) |
| **Database** | Cloud SQL for PostgreSQL |
| **RAG** | Vertex AI Search — SOP corpus + field learnings corpus |
| **Integrations** | MCP servers for QuickBooks Online and LinkedIn |
| **Chat agents** | Google Chat (internal) + Slack (external) |

## Quick start

There are two development modes depending on whether you want to run everything locally or connect to the live GCP environment.

### Option A — Fully local (Docker Compose)

Runs the entire stack on your machine. No GCP charges.

**Prerequisites:** Docker & Docker Compose, Node.js 18+

```bash
cp .env.example .env          # first time — paste your Gemini API key
docker compose up -d           # Postgres :5432, orchestrator :8080, MCP stubs :9001/:9002
cd web && npm install          # first time only
npm run dev                    # Web app at http://localhost:5173
```

The `init-scripts/` directory bootstraps the Postgres schema automatically on first boot.

### Option B — GCP proxy mode

Connects to the live Cloud Run services on GCP through authenticated local tunnels. Uses the real database, real Gemini agent, and real MCP adapters.

**Prerequisites:** `gcloud` CLI authenticated, `cloud-run-proxy` component installed

```bash
./deployment/scripts/dev-gcp-proxy.sh
```

This single command starts:
- **http://localhost:8080** — Orchestrator API (proxied from Cloud Run)
- **http://localhost:5173** — Web app (Vite dev server, pointed at the proxy)
- **http://localhost:8080/docs** — FastAPI Swagger docs

Press `Ctrl-C` to stop everything.

The `gcloud run services proxy` command handles authentication transparently — your browser hits `localhost`, the proxy injects your GCP identity token, and forwards to Cloud Run. No tokens needed in the browser.

### Explore

- **Visits table** — create service requests, track states and pay status
- **Finance table** — review/approve/reject contractor payouts
- **Swagger docs** — http://localhost:8080/docs
- **Dev auth** — toggle Technician/Finance Manager roles in the header bar

### End-to-end test

Walk a visit through the full lifecycle (works in both modes):

```bash
# 1. Create a service visit
curl -s -X POST http://localhost:8080/api/v1/visits \
  -H 'Content-Type: application/json' \
  -H 'X-User-Email: tech@roboreliance.internal' \
  -H 'X-User-Role: technician' \
  -d '{
    "location_string": "Denver DC Rack 12",
    "metadata_poc": {
      "name": "Alex Kim",
      "phone": "+13035550123",
      "email": "alex@example.com"
    }
  }' | jq .

# Save the visit_id from the response, then:
VISIT_ID="<paste-visit-id>"

# 2. Clock in
curl -s -X POST "http://localhost:8080/api/v1/visits/$VISIT_ID/clock-in" \
  -H 'Content-Type: application/json' \
  -H 'X-User-Email: tech@roboreliance.internal' \
  -H 'X-User-Role: technician' \
  -d '{}' | jq .

# 3. Sign off (triggers billing calculation)
curl -s -X POST "http://localhost:8080/api/v1/visits/$VISIT_ID/signoff" \
  -H 'Content-Type: application/json' \
  -H 'X-User-Email: tech@roboreliance.internal' \
  -H 'X-User-Role: technician' \
  -d '{
    "clock_in": "2026-07-03T08:00:00Z",
    "clock_out": "2026-07-03T12:30:00Z",
    "findings": "Replaced actuator belt and recalibrated torque sensors."
  }' | jq .

# 4. Check the visit — should be pending_approval with a financial ledger
curl -s "http://localhost:8080/api/v1/visits/$VISIT_ID" \
  -H 'X-User-Email: tech@roboreliance.internal' \
  -H 'X-User-Role: technician' | jq .

# 5. Review pending finance items (as finance manager)
curl -s "http://localhost:8080/api/v1/finance/ledgers?approval_state=pending_review" \
  -H 'X-User-Email: finance@roboreliance.internal' \
  -H 'X-User-Role: finance_manager' | jq .

# 6. Approve (paste the approval_token from signoff response)
curl -s -X POST http://localhost:8080/api/v1/finance/approve \
  -H 'Content-Type: application/json' \
  -H 'X-User-Email: finance@roboreliance.internal' \
  -H 'X-User-Role: finance_manager' \
  -d '{
    "approval_token": "<paste-token>",
    "action": "approve"
  }' | jq .
```

**Expected state progression:** `initiated` → `active` (clock-in) → `pending_approval` (sign-off) → `completed` (finance approved)

## Project structure

```
├── orchestrator/          # FastAPI backend + ADK agent
│   ├── main.py            # App entrypoint, webhook routes
│   ├── api_v1.py          # REST API for web app
│   ├── agent_def.py       # ADK agent + tool definitions
│   ├── agent_runner.py    # Shared agent turn processor
│   ├── database.py        # PostgreSQL data layer
│   ├── auth.py            # IAP + dev header auth
│   └── ...
├── web/                   # React SPA (Vite)
│   ├── src/pages/         # Visits, Finance, NewVisit pages
│   ├── src/api/client.ts  # Typed API client
│   └── src/components/    # WebChat, shared UI
├── mcp-servers/           # Mock MCP adapters (QuickBooks, LinkedIn)
├── init-scripts/          # SQL schema bootstrap
├── deployment/            # Terraform, Cloud Build, setup guides
│   ├── terraform/         # GCP infrastructure as code
│   ├── cloudbuild/        # CI/CD pipeline
│   └── docs/              # Deployment-specific guides
├── docs/                  # Architecture & strategy docs
└── docker-compose.yml     # Local development stack
```

## Documentation

| Document | Purpose |
|----------|---------|
| [docs/system_spec.md](docs/system_spec.md) | Full system architecture, schema, workflow, and ADK agent spec |
| [docs/UI_STRATEGY.md](docs/UI_STRATEGY.md) | Four-surface UI model: web app, web chat, Google Chat, Slack |
| [docs/CONTEXT.md](docs/CONTEXT.md) | Compact project context for AI-assisted development |
| [deployment/GCP_CHECKLIST.md](deployment/GCP_CHECKLIST.md) | Phased GCP deployment runbook |
| [deployment/docs/GOOGLE_CHAT_SETUP.md](deployment/docs/GOOGLE_CHAT_SETUP.md) | Google Chat app registration + Slack event config |

## API surfaces

| Surface | Endpoint | Purpose |
|---------|----------|---------|
| Web app REST API | `POST /api/v1/visits` | Service request intake |
| | `GET /api/v1/visits` | Visits table (filterable) |
| | `GET /api/v1/finance/ledgers` | Finance table (filterable) |
| | `POST /api/v1/finance/approve` | Approve/reject payouts |
| | `POST /api/v1/web-chat/message` | Embedded NL chat |
| Slack agent | `POST /webhooks/slack` | Channel listening + NL timekeeping |
| Google Chat agent | `POST /webhooks/google-chat` | Internal visit spaces + RAG |
| Finance webhook | `POST /webhooks/finance` | Programmatic approve/reject |

## Deployment

Infrastructure is managed with Terraform in `deployment/terraform/single-project/`. Application images are built and deployed via Cloud Build (`deployment/cloudbuild/build-images.yaml`).

See the [GCP Checklist](deployment/GCP_CHECKLIST.md) for the full deployment runbook.
