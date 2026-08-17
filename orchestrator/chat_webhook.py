"""
Google Chat webhook handler — internal visit spaces and invitable agent.

Supports both payload shapes:
  - Classic Chat Event: root `type` / `message` / `space`
  - Workspace Add-on: `chat.messagePayload` / `chat.addedToSpacePayload` / …

Response shape matches the inbound format (classic `{"text": ...}` vs
add-on `hostAppDataAction.chatDataAction.createMessageAction`).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional, Tuple

from agent_runner import ChannelContext, handle_agent_turn
from database import get_visit_by_google_space_id
from field_learnings_ingest import ingest_chat_message

logger = logging.getLogger(__name__)


def _is_addon_event(payload: dict[str, Any]) -> bool:
    chat = payload.get("chat")
    return isinstance(chat, dict) and bool(chat)


def _normalize_event(payload: dict[str, Any]) -> Tuple[str, dict[str, Any], dict[str, Any], dict[str, Any]]:
    """
    Return (event_type, space, message, user) for classic or add-on payloads.
    """
    if _is_addon_event(payload):
        chat = payload.get("chat") or {}
        user = chat.get("user") or {}
        if "messagePayload" in chat:
            body = chat.get("messagePayload") or {}
            return "MESSAGE", body.get("space") or {}, body.get("message") or {}, user
        if "addedToSpacePayload" in chat:
            body = chat.get("addedToSpacePayload") or {}
            return (
                "ADDED_TO_SPACE",
                body.get("space") or {},
                body.get("message") or {},
                user,
            )
        if "removedFromSpacePayload" in chat:
            body = chat.get("removedFromSpacePayload") or {}
            return (
                "REMOVED_FROM_SPACE",
                body.get("space") or {},
                {},
                user,
            )
        if "appCommandPayload" in chat:
            body = chat.get("appCommandPayload") or {}
            return "MESSAGE", body.get("space") or {}, body.get("message") or {}, user
        logger.info("Unrecognized Google Chat add-on payload keys: %s", list(chat.keys()))
        return "", {}, {}, user

    event_type = payload.get("type") or payload.get("eventType") or ""
    return (
        str(event_type),
        payload.get("space") or {},
        payload.get("message") or {},
        payload.get("user") or {},
    )


def _chat_text(message: dict[str, Any]) -> str:
    text = message.get("text", "") or message.get("argumentText", "")
    return text.strip()


def _chat_user_email(user: dict[str, Any], message: dict[str, Any]) -> str:
    sender = user or message.get("sender") or {}
    return (
        sender.get("email")
        or (sender.get("name", "").replace("users/", "") + "@google.chat")
        or "unknown@roboreliance.internal"
    )


def build_google_chat_response(text: str, *, addon: bool = False) -> dict[str, Any]:
    if not (text or "").strip():
        return {}
    message = {"text": text.strip()}
    if addon:
        return {
            "hostAppDataAction": {
                "chatDataAction": {
                    "createMessageAction": {
                        "message": message,
                    }
                }
            }
        }
    return message


def handle_google_chat_event(payload: dict[str, Any]) -> dict[str, Any]:
    addon = _is_addon_event(payload)
    event_type, space, message, user = _normalize_event(payload)
    space_name = space.get("name", "") if isinstance(space, dict) else ""

    visit = get_visit_by_google_space_id(space_name) if space_name else None
    visit_id = str(visit["visit_id"]) if visit else None

    if event_type in {"ADDED_TO_SPACE", "added_to_space"}:
        if visit:
            return build_google_chat_response(
                f"Robo Reliance field agent online for visit at {visit['location_string']} "
                f"(state: {visit['current_state']}). Ask SOP questions or say 'clock in' / 'clock out'.",
                addon=addon,
            )
        return build_google_chat_response(
            "Robo Reliance field agent online. I can answer SOP and field-learning questions. "
            "Bind this space to a visit for timekeeping.",
            addon=addon,
        )

    if event_type in {"REMOVED_FROM_SPACE", "removed_from_space"}:
        logger.info("Agent removed from space %s — final ingestion sweep", space_name)
        return {}

    if event_type in {"MESSAGE", "message"} and message:
        text = _chat_text(message)
        if not text:
            logger.info("Google Chat MESSAGE with empty text (space=%s)", space_name)
            return {}

        user_email = _chat_user_email(user, message)
        message_name = message.get("name", f"msg-{datetime.now(timezone.utc).timestamp()}")
        thread = message.get("thread", {}) or {}
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
        return build_google_chat_response(turn.reply_text, addon=addon)

    logger.info(
        "Unhandled Google Chat event (addon=%s type=%r keys=%s)",
        addon,
        event_type,
        list(payload.keys()),
    )
    return {}
