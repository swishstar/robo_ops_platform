"""
Google Chat webhook handler — internal visit spaces and invitable agent.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from agent_runner import ChannelContext, handle_agent_turn
from database import get_visit_by_google_space_id
from field_learnings_ingest import ingest_chat_message

logger = logging.getLogger(__name__)


def _chat_text(message: dict[str, Any]) -> str:
    text = message.get("text", "") or message.get("argumentText", "")
    return text.strip()


def _chat_user_email(event: dict[str, Any]) -> str:
    user = event.get("user", {}) or event.get("message", {}).get("sender", {})
    return (
        user.get("email")
        or user.get("name", "").replace("users/", "") + "@google.chat"
        or "unknown@roboreliance.internal"
    )


def build_google_chat_response(text: str) -> dict[str, Any]:
    return {"text": text}


def handle_google_chat_event(payload: dict[str, Any]) -> dict[str, Any]:
    event_type = payload.get("type") or payload.get("eventType", "")
    space = payload.get("space", {})
    space_name = space.get("name", "")
    message = payload.get("message", {})

    visit = get_visit_by_google_space_id(space_name) if space_name else None
    visit_id = str(visit["visit_id"]) if visit else None

    if event_type in {"ADDED_TO_SPACE", "added_to_space"}:
        if visit:
            return build_google_chat_response(
                f"Robo Reliance field agent online for visit at {visit['location_string']} "
                f"(state: {visit['current_state']}). Ask SOP questions or say 'clock in' / 'clock out'."
            )
        return build_google_chat_response(
            "Robo Reliance field agent online. I can answer SOP and field-learning questions. "
            "Bind this space to a visit for timekeeping."
        )

    if event_type in {"REMOVED_FROM_SPACE", "removed_from_space"}:
        logger.info("Agent removed from space %s — final ingestion sweep", space_name)
        return {}

    if event_type in {"MESSAGE", "message"} and message:
        text = _chat_text(message)
        if not text:
            return {}

        user_email = _chat_user_email(payload)
        message_name = message.get("name", f"msg-{datetime.now(timezone.utc).timestamp()}")
        thread = message.get("thread", {})
        thread_name = thread.get("name")

        ingest_chat_message(
            channel_type="google_chat",
            channel_id=space_name,
            message_id=message_name,
            text=text,
            author=user_email,
            visit_id=visit_id,
            thread_id=thread_name,
        )

        context = ChannelContext(
            surface="google_chat",
            channel_id=space_name,
            thread_id=thread_name,
            visit_id=visit_id,
            user_identity=user_email,
        )
        turn = handle_agent_turn(text, context)
        return build_google_chat_response(turn.reply_text)

    return {}
