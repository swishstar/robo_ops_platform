"""
Slack Events API handler — parallel to Google Chat for external/client channels.

Exposed at POST /webhooks/slack. Visit creation is handled by the web app
(POST /api/v1/visits); Slack can call that API to create visits programmatically.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from agent_runner import ChannelContext, handle_agent_turn
from database import get_visit_by_slack_channel_id
from field_learnings_ingest import ingest_chat_message

logger = logging.getLogger(__name__)


def _slack_text(event: dict[str, Any]) -> str:
    return (event.get("text") or "").strip()


def _slack_user_email(event: dict[str, Any]) -> str:
    return event.get("user_email") or f"slack:{event.get('user', 'unknown')}@roboreliance.internal"


def handle_slack_event(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("type") == "url_verification":
        return {"challenge": payload.get("challenge", "")}

    if payload.get("type") != "event_callback":
        return {}

    event = payload.get("event", {})
    event_type = event.get("type", "")

    if event_type not in {"message", "app_mention"}:
        return {}

    if event.get("bot_id") or event.get("subtype") == "bot_message":
        return {}

    channel_id = event.get("channel", "")
    text = _slack_text(event)
    if not text:
        return {}

    visit = get_visit_by_slack_channel_id(channel_id) if channel_id else None
    visit_id = str(visit["visit_id"]) if visit else None

    user_email = _slack_user_email(event)
    message_ts = event.get("ts", str(datetime.now(timezone.utc).timestamp()))
    thread_ts = event.get("thread_ts")

    ingest_chat_message(
        channel_type="slack",
        channel_id=channel_id,
        message_id=message_ts,
        text=text,
        author=user_email,
        visit_id=visit_id,
        thread_id=thread_ts,
    )

    context = ChannelContext(
        surface="slack",
        channel_id=channel_id,
        thread_id=thread_ts,
        visit_id=visit_id,
        user_identity=user_email,
    )
    turn = handle_agent_turn(text, context)

    return {
        "response_type": "in_channel",
        "text": turn.reply_text,
        "visit_id": visit_id,
        "citations": turn.citations,
    }
