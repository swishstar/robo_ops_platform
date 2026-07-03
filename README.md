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

### Prerequisites

- Docker & Docker Compose
- Node.js 18+
- (Optional) `GOOGLE_API_KEY` for Gemini-powered agent responses

### 1. Start the backend

```bash
docker compose up -d
```

This starts Postgres (`:5432`), the orchestrator (`:8080`), and MCP stub servers (`:9001`, `:9002`). The `init-scripts/` directory bootstraps the database schema automatically.

### 2. Start the frontend

```bash
cd web
npm install   # first time only
npm run dev
```

Opens at **http://localhost:5173**. The Vite dev server proxies `/api/*` to the orchestrator.

### 3. Explore

- **Visits table** — create service requests, track states and pay status
- **Finance table** — review/approve/reject contractor payouts
- **Swagger docs** — http://localhost:8080/docs
- **Dev auth** — toggle Technician/Finance Manager roles in the header bar

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
