# Google Chat App Registration

Register the Inner Loop field agent in GCP Console after deploying the orchestrator.

## Prerequisites

- `chat.googleapis.com` enabled (Terraform `apis.tf`)
- Orchestrator URL: `terraform output -raw orchestrator_url`

## Configuration

1. Open [Google Cloud Console -> APIs & Services -> Google Chat API -> Configuration](https://console.cloud.google.com/apis/api/chat.googleapis.com/hangouts-chat)
2. Create or edit the Chat app:
   - **App name:** Robo Reliance Field Agent
   - **Avatar:** optional
   - **Description:** Internal visit support, SOP RAG, field learnings, timekeeping
3. **Functionality:**
   - Receive 1:1 messages: **On**
   - Join spaces and group conversations: **On**
4. **Connection settings:**
   - **HTTP endpoint URL:** `{ORCHESTRATOR_URL}/webhooks/google-chat`
5. **Visibility:** Domain-only or specific spaces per your Workspace policy
6. Save and publish

## Visit space binding

When a new service request is created (via the web app at `POST /api/v1/visits`), the orchestrator provisions:

- `visits.slack_channel_id` — external/client Slack channel (optional, can be linked later)
- `visits.google_space_id` — internal Google Chat space for field team

Invite the Chat app to the internal Google space. `ADDED_TO_SPACE` events match `google_space_id` automatically.

## Slack (parallel)

Configure Slack Event Subscriptions:

- **Request URL:** `{ORCHESTRATOR_URL}/webhooks/slack`
- Subscribe to `message.channels`, `app_mention`

New visit requests are created via the web app or by calling `POST /api/v1/visits` programmatically from Slack workflows.

See [docs/UI_STRATEGY.md](../../docs/UI_STRATEGY.md) for the four-surface model (Web App, Web Chat, Google Chat, Slack).
