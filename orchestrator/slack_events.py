"""
Slack Events API handler — parallel to Google Chat for external/client channels.

Exposed at POST /webhooks/slack. Visit creation is handled by the web app
(POST /api/v1/visits); Slack can call that API to create visits programmatically.

Events API does not display the HTTP response body in-channel. After the agent
turn, replies are posted via chat.postMessage (see slack_client.py).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from agent_runner import ChannelContext, handle_agent_turn
from database import get_visit_by_slack_channel_id
from field_learnings_ingest import ingest_chat_message
from slack_client import post_channel_message

logger = logging.getLogger(__name__)


def _slack_text(event: dict[str, Any]) -> str:
    return (event.get("text") or "").strip()


def _slack_user_email(event: dict[str, Any]) -> str:
    return event.get("user_email") or f"slack:{event.get('user', 'unknown')}@roboreliance.internal"


def handle_slack_url_verification(payload: dict[str, Any]) -> dict[str, Any]:
    return {"challenge": payload.get("challenge", "")}


def process_slack_event(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Ingest a Slack event_callback, run the agent, and post the reply to the channel.

    Safe to run from a FastAPI BackgroundTask after acknowledging Slack with 200.
    """
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
    reply_text = (turn.reply_text or "").strip()
    if not reply_text:
        logger.info(
            "Slack agent returned empty reply (channel=%s visit=%s); skipping postMessage",
            channel_id,
            visit_id,
        )
        return {"visit_id": visit_id, "posted": False}

    # Reply in-thread when the user messaged in a thread; otherwise top-level.
    # For bare @mentions, thread under the mention so the channel stays quieter.
    reply_thread_ts: Optional[str] = thread_ts or message_ts

    try:
        post_channel_message(
            channel_id,
            reply_text,
            thread_ts=reply_thread_ts,
        )
        logger.info(
            "Posted Slack reply (channel=%s visit=%s thread=%s)",
            channel_id,
            visit_id,
            reply_thread_ts,
        )
    except Exception:
        logger.exception(
            "Failed to post Slack reply (channel=%s visit=%s)",
            channel_id,
            visit_id,
        )
        raise

    return {
        "visit_id": visit_id,
        "posted": True,
        "citations": turn.citations,
    }


def handle_slack_event(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Synchronous entrypoint (tests / local). Prefer process_slack_event from the
    webhook after URL verification is handled separately.
    """
    if payload.get("type") == "url_verification":
        return handle_slack_url_verification(payload)
    return process_slack_event(payload)
