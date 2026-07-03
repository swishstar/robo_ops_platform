# UI Strategy: Ops Web App + Three Chat Surfaces

## Overview

The Inner Loop platform exposes **four distinct user interfaces** that share one deterministic backend:

| Surface | Audience | Purpose |
|---------|----------|---------|
| **Ops & Finance Web App** | Technicians, finance managers, clients | Service request intake, timekeeping, finance approval/history, embedded **Web Chat** |
| **Web Chat** (embedded in web app) | Authenticated web users | NL questions about process/data, commands — **not** channel listening |
| **Google Chat agent** | Internal field team | Invited to **internal visit spaces**; RAG, knowledge capture, NL clock in/out |
| **Slack agent** | Client-facing + external | **External/client Slack channels**; RAG, knowledge capture, NL clock in/out |

**Core constraint (unchanged):** AI interprets and suggests; deterministic Python tools validate and commit.

---

## Service request intake

The **web app** is the primary intake surface. New service requests are created via `POST /api/v1/visits` from the "New Service Request" page. Slack can call this same API endpoint programmatically to submit requests from external channels.

There is no dedicated Slack intake webhook. The old `/webhooks/slack/intake` has been retired.

---

## Channel roles: Slack vs Google Chat

These are **parallel channel integrations** for agent listening, not interchangeable:

| | **Slack** | **Google Chat** |
|---|-----------|-----------------|
| **Primary use** | Client communication, external technical discussion | Internal visit coordination |
| **Visit binding** | `visits.slack_channel_id` | `visits.google_space_id` |
| **Agent listening** | `POST /webhooks/slack` | `POST /webhooks/google-chat` |
| **Knowledge ingest** | `slack` channel type -> `field_learnings` index | `google_chat` channel type -> `field_learnings` index |

Both Slack and Google Chat agents use the **same agent tool surface** (`agent_runner.py`) and can trigger clock in/out via natural language.

## Web Chat vs channel agents

| | **Web Chat** | **Google Chat / Slack channel agents** |
|---|--------------|----------------------------------------|
| **Where** | Embedded panel in Ops web app | Invited/listening in workspace channels |
| **API** | `POST /api/v1/web-chat/message` | `/webhooks/google-chat`, `/webhooks/slack` |
| **Session** | Per authenticated user (`web:{email}:{visit_id}`) | Per space/channel + thread |
| **Reads channel history** | No | Yes (ingested into field learnings) |
| **Timekeeping** | NL via shared tools + structured forms | NL via shared tools (`clock in` / `clock out`) |

Web Chat is **additional infrastructure** on top of channel agents — not a replacement for them.

---

## Ops & Finance Web App

### Technician screens
- **Visits table** — filterable by state; defaults to active/upcoming; can toggle to show all including completed
- Each row shows location, state, assigned technician, pay status, and payout amount
- **+ New Service Request** — form to capture location, POC (name, phone, email), optional Slack channel
- **Visit detail** — location, POC, linked channels, timekeeping panel, embedded Web Chat
- **Timekeeping panel** — Clock In / Sign Off with findings

### Finance manager screens
- **Finance table** — all invoices/ledgers, filterable by status; defaults to pending_review
- Columns: location, status, technician, hours, invoice, payout, QBO ref, date
- **Ledger detail** — full breakdown, approve/reject actions, audit trail, embedded Web Chat

### Embedded Web Chat
- Side panel or tab on visit detail and finance views
- Session key: `web:{user_email}:{visit_id|global}`

---

## API contract (`/api/v1/*`)

Authenticated via IAP JWT (production) or `X-User-Email` / `X-User-Role` headers (development).

```
POST /api/v1/visits                           # create new service request
GET  /api/v1/visits?state=&technician=&include_completed=
GET  /api/v1/visits/{visit_id}
POST /api/v1/visits/{visit_id}/clock-in
POST /api/v1/visits/{visit_id}/signoff
GET  /api/v1/finance/ledgers?approval_state=  # filterable table
GET  /api/v1/finance/pending
GET  /api/v1/finance/ledger/{ledger_id}
POST /api/v1/finance/approve
POST /api/v1/web-chat/message
```

---

## Webhook matrix

### Google Chat (`POST /webhooks/google-chat`)

| Event | Behavior |
|-------|----------|
| `ADDED_TO_SPACE` | Match `space.name` to `visits.google_space_id`; onboarding reply |
| `MESSAGE` | Route to ADK agent; enqueue field-learnings ingestion |
| `REMOVED_FROM_SPACE` | Final ingestion sweep |

### Slack (`POST /webhooks/slack`)

| Event | Behavior |
|-------|----------|
| `url_verification` | Return challenge |
| `message` (in bound channel) | Route to ADK agent; enqueue ingestion |
| App mention | Same as message |

### Finance (`POST /webhooks/finance`)

External finance gateway for programmatic approve/reject (e.g. from Slack bots or automation).

---

## RAG dual corpus

- **SOP** (`lookup_technical_sop`): Google Drive `/03_Technical_Library`
- **Field learnings** (`lookup_field_learnings`): auto-indexed from Google Chat + Slack channels

Agent prefers SOP for authoritative answers; surfaces field learnings for novel on-site discoveries.

---

## Security boundaries

| Data | Web app | Web Chat | Google Chat | Slack |
|------|---------|----------|-------------|-------|
| Visit creation | Read/write | — | — | Via API |
| Labor / findings | Read/write | Tool-mediated write | Tool-mediated write | Tool-mediated write |
| Payout / approval | Manager only | No access | No access | No access |
| Field learnings ingest | — | — | Auto | Auto |

Finance approval tokens and payout amounts are never indexed into field learnings.
