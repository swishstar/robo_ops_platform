# Google Chat App Registration

Register the Inner Loop field agent in GCP Console after deploying the orchestrator.

## Prerequisites

- `chat.googleapis.com` enabled (Terraform `apis.tf`)
- Orchestrator URL: `terraform output -raw orchestrator_url`
- Webhook URL: `terraform output -raw google_chat_webhook_url`
- Under domain-restricted sharing, `chat@system.gserviceaccount.com` cannot be granted `roles/run.invoker`. Use `orchestrator_invoker_iam_disabled = true` and rely on app-level JWT verification (`orchestrator/webhook_security.py`).

## Configuration

1. Open [Google Cloud Console → APIs & Services → Google Chat API → Configuration](https://console.cloud.google.com/apis/api/chat.googleapis.com/hangouts-chat?project=robo-reliance-ops)
2. Create or edit the Chat app:
   - **App name:** Robo Reliance Field Agent
   - **Avatar:** optional
   - **Description:** Internal visit support, SOP RAG, field learnings, timekeeping
3. **Functionality:**
   - Receive 1:1 messages: **On**
   - Join spaces and group conversations: **On**
4. **Connection settings:**
   - **HTTP endpoint URL:** `{ORCHESTRATOR_URL}/webhooks/google-chat`
     - Do **not** append `/events` — that path 404s on the orchestrator
   - Newer Console UIs may show **Service Account Email**
     (`service-PROJECT_NUMBER@gcp-sa-gsuiteaddons.iam.gserviceaccount.com`) and
     omit **Authentication audience**. That is fine: audience is the HTTP endpoint URL.
   - If you still see **Authentication audience**, prefer **HTTP endpoint URL**
     (or **Project number** `611591209386`)
5. **Visibility:** Domain-only or specific spaces per Workspace policy
6. Save and publish

## Verification (already in orchestrator)

`POST /webhooks/google-chat` validates the `Authorization: Bearer` token via `orchestrator/webhook_security.py`:

- HTTP-endpoint audience → OIDC ID token, `email == chat@system.gserviceaccount.com`
- Project-number audience → JWT signed by Chat SA certs, `iss == chat@system.gserviceaccount.com`

Env vars (set by Terraform): `GOOGLE_CHAT_AUDIENCE`, `GOOGLE_CLOUD_PROJECT_NUMBER`.

## Visit space binding

When a new service request is created (via the web app at `POST /api/v1/visits`), the orchestrator provisions:

- `visits.slack_channel_id` — external/client Slack channel (optional, can be linked later)
- `visits.google_space_id` — internal Google Chat space for field team

Invite the Chat app to the internal Google space. `ADDED_TO_SPACE` events match `google_space_id` automatically.

## Slack (parallel)

Configure Slack Event Subscriptions:

- **Request URL:** `{ORCHESTRATOR_URL}/webhooks/slack`
- Subscribe to `message.channels`, `app_mention`
- Store the **signing secret** (Basic Information → App Credentials):
  ```bash
  echo -n 'YOUR_SLACK_SIGNING_SECRET' | gcloud secrets versions add \
    inner-loop-slack-signing-secret-dev \
    --project=robo-reliance-ops --data-file=-
  ```
- Store the **Bot User OAuth Token** (OAuth & Permissions → Bot User OAuth Token, `xoxb-…`).
  Requires bot scope `chat:write` (plus `app_mentions:read`, `channels:history`):
  ```bash
  echo -n 'xoxb-YOUR_BOT_TOKEN' | gcloud secrets versions add \
    inner-loop-slack-bot-token-dev \
    --project=robo-reliance-ops --data-file=-
  ```
- After either secret update, refresh the Cloud Run revision:
  ```bash
  gcloud run services update inner-loop-orchestrator \
    --region=us-central1 --project=robo-reliance-ops \
    --update-secrets=SLACK_SIGNING_SECRET=inner-loop-slack-signing-secret-dev:latest,SLACK_BOT_TOKEN=inner-loop-slack-bot-token-dev:latest
  ```
- Under org policy that blocks `allUsers`, `orchestrator_invoker_iam_disabled = true` is required so Slack can reach the endpoint (app HMAC verification remains required).

Replies are posted with `chat.postMessage` (Events API does not show the HTTP response body in-channel).

New visit requests are created via the web app or by calling `POST /api/v1/visits` programmatically from Slack workflows.

See [docs/UI_STRATEGY.md](../../docs/UI_STRATEGY.md) for the four-surface model (Web App, Web Chat, Google Chat, Slack).
