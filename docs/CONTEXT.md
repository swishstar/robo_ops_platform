# Project Context (AI-Optimized)

Use this file to quickly orient on the codebase. For deep dives, follow the links.

## What this is

Field operations platform for **Robo Reliance** — manages service visits, technician timekeeping, contractor payouts, and knowledge capture. Built on GCP with a Gemini-powered ADK agent.

## Core constraint

AI interprets; **deterministic Python tools validate and execute**. The LLM never writes directly to the database or triggers external mutations. Every transaction flows through handcoded validation in ADK tool functions.

## Tech stack

- **Backend:** FastAPI (Python 3.9+), Google ADK, psycopg2/asyncpg, Cloud Run
- **Frontend:** React 18 + TypeScript, Vite, TanStack Query, react-router-dom
- **Database:** PostgreSQL (Cloud SQL) — schema in `init-scripts/`
- **RAG:** Vertex AI Search — dual corpus (SOP + field learnings)
- **Integrations:** MCP JSON-RPC servers for QuickBooks and LinkedIn
- **Chat:** Google Chat agent (internal), Slack agent (external)
- **Auth:** IAP JWT (production), `X-User-Email`/`X-User-Role` headers (dev)
- **Infra:** Terraform (`deployment/terraform/`), Cloud Build (`deployment/cloudbuild/`)

## Four UI surfaces

1. **Ops Web App** (`web/`) — service request intake, visits table, finance table, timekeeping
2. **Web Chat** — embedded NL panel in the web app (`POST /api/v1/web-chat/message`)
3. **Google Chat agent** — invited to internal visit spaces (`POST /webhooks/google-chat`)
4. **Slack agent** — external/client channels (`POST /webhooks/slack`)

## Key directories

| Path | Contents |
|------|----------|
| `orchestrator/` | FastAPI app, ADK agent, tools, database layer, webhook handlers |
| `orchestrator/main.py` | App entrypoint — health, webhooks (`/webhooks/slack`, `/webhooks/google-chat`, `/webhooks/finance`) |
| `orchestrator/api_v1.py` | Authenticated REST API (`/api/v1/*`) — visits CRUD, finance, web chat |
| `orchestrator/agent_def.py` | ADK agent definition + tool functions (`process_visit_signoff`, `lookup_technical_sop`, etc.) |
| `orchestrator/agent_runner.py` | Shared agent turn processor for all chat surfaces |
| `orchestrator/database.py` | All PostgreSQL queries — `create_visit`, `list_visits`, `list_finance_ledgers`, etc. |
| `orchestrator/auth.py` | Auth middleware — IAP (prod) / header-based (dev) |
| `web/src/` | React SPA source |
| `web/src/api/client.ts` | Typed API client + data interfaces |
| `web/src/pages/` | `VisitsPage`, `NewVisitPage`, `VisitDetailPage`, `FinanceQueuePage`, `FinanceDetailPage` |
| `init-scripts/` | SQL files auto-run by Postgres on first boot |
| `deployment/terraform/single-project/` | GCP Terraform configs (Cloud Run, Cloud SQL, IAM, APIs) |
| `docs/` | Architecture docs — `system_spec.md`, `UI_STRATEGY.md`, this file |

## Database tables

| Table | Purpose |
|-------|---------|
| `visits` | Service visit records — location, POC, state, linked channel IDs |
| `labor_logs` | Technician clock in/out + findings per visit |
| `financial_ledgers` | Invoice/payout amounts, approval state per visit |
| `immutable_audit_trail` | Append-only log of every system action |
| `finance_approval_tokens` | One-time tokens for HITL finance approval |
| `platform_configs` | Key-value runtime configuration |
| `channel_ingestion_cursors` | Tracks last-ingested message per chat channel |
| `space_visit_bindings` | Maps Google Chat space → visit |
| `slack_channel_visit_bindings` | Maps Slack channel → visit |
| `web_chat_sessions` | Tracks authenticated web chat sessions |

## API routes

**REST API** (auth required, prefix `/api/v1`):
- `POST /visits` — create service request
- `GET /visits?state=&technician=&include_completed=` — filterable visits table
- `GET /visits/{id}` — visit detail + labor logs + ledgers
- `POST /visits/{id}/clock-in` | `POST /visits/{id}/signoff`
- `GET /finance/ledgers?approval_state=` — filterable finance table
- `GET /finance/pending` | `GET /finance/ledger/{id}` | `POST /finance/approve`
- `POST /web-chat/message` — embedded NL chat

**Webhooks** (no auth middleware — verified by platform):
- `POST /webhooks/slack` — Slack Events API
- `POST /webhooks/google-chat` — Google Chat events
- `POST /webhooks/finance` — programmatic approve/reject

## Workflow states

`initiated` → `active` (clock-in) → `pending_approval` (sign-off) → `completed` (finance approved) or `failed`

## Dev environment

```bash
docker compose up -d          # Postgres + orchestrator + MCP stubs
cd web && npm run dev          # React dev server at :5173
# Orchestrator at :8080, Swagger at :8080/docs
```

## Deep-dive docs

- [docs/system_spec.md](system_spec.md) — full architecture, schema DDL, ADK agent spec
- [docs/UI_STRATEGY.md](UI_STRATEGY.md) — four-surface model, API contract, security boundaries
- [deployment/GCP_CHECKLIST.md](../deployment/GCP_CHECKLIST.md) — phased deployment runbook
