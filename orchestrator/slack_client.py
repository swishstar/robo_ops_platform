"""
Slack Web API helpers — post replies after Events API ingestion.

Events API HTTP responses are not shown in channel; replies require chat.postMessage
with a bot token (xoxb-...).
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

SLACK_API_BASE = "https://slack.com/api"
DEFAULT_TIMEOUT_SECONDS = float(os.getenv("SLACK_HTTP_TIMEOUT_SECONDS", "15"))


def _bot_token() -> Optional[str]:
    token = os.getenv("SLACK_BOT_TOKEN", "").strip()
    return token or None


def post_channel_message(
    channel_id: str,
    text: str,
    *,
    thread_ts: Optional[str] = None,
) -> dict[str, Any]:
    """
    Post a message to a Slack channel (and optional thread).

    Returns the Slack API JSON body. Raises RuntimeError when the token is missing
    or Slack returns ok=false.
    """
    token = _bot_token()
    if not token:
        raise RuntimeError(
            "SLACK_BOT_TOKEN is not configured; cannot post chat.postMessage replies."
        )
    if not channel_id:
        raise RuntimeError("Slack channel_id is required to post a message.")
    if not (text or "").strip():
        raise RuntimeError("Slack message text is empty.")

    payload: dict[str, Any] = {
        "channel": channel_id,
        "text": text.strip(),
    }
    if thread_ts:
        payload["thread_ts"] = thread_ts

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }

    with httpx.Client(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
        response = client.post(
            f"{SLACK_API_BASE}/chat.postMessage",
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
        body = response.json()

    if not body.get("ok"):
        error = body.get("error", "unknown_error")
        logger.error("Slack chat.postMessage failed: %s (%s)", error, body)
        raise RuntimeError(f"Slack chat.postMessage failed: {error}")

    return body
