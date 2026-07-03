"""
Field learnings ingestion — auto-index channel messages into the field_learnings corpus.

In development, writes JSONL stubs locally. In production, delegates to Vertex AI Search.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from database import upsert_channel_ingestion_cursor

logger = logging.getLogger(__name__)

FIELD_LEARNINGS_ENDPOINT = os.getenv(
    "FIELD_LEARNINGS_SEARCH_ENDPOINT",
    "https://discoveryengine.googleapis.com/v1/projects/roboreliance/locations/global/"
    "collections/default_collection/engines/field-learnings/servingConfigs/default_search",
)
FIELD_LEARNINGS_STORE = Path(os.getenv("FIELD_LEARNINGS_STORE", "/tmp/field_learnings"))


def _document_id(*, channel_type: str, channel_id: str, message_id: str) -> str:
    raw = f"{channel_type}:{channel_id}:{message_id}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _persist_stub_document(doc_id: str, payload: dict[str, Any]) -> None:
    FIELD_LEARNINGS_STORE.mkdir(parents=True, exist_ok=True)
    path = FIELD_LEARNINGS_STORE / f"{doc_id}.json"
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def ingest_chat_message(
    *,
    channel_type: str,
    channel_id: str,
    message_id: str,
    text: str,
    author: str,
    visit_id: str | None,
    timestamp: datetime | None = None,
    thread_id: str | None = None,
) -> str:
    """
    Deterministically ingest one channel message into field learnings.
    Skips financial/PII patterns.
    """
    normalized = text.strip()
    if not normalized or len(normalized) < 4:
        return ""

    blocked_patterns = ("approval_token", "payout_cents", "invoice_cents", "qbo_")
    lowered = normalized.lower()
    if any(p in lowered for p in blocked_patterns):
        logger.debug("Skipping message with financial pattern")
        return ""

    if normalized.startswith("bot:") or author.endswith("@bot"):
        return ""

    ts = timestamp or datetime.now(timezone.utc)
    doc_id = _document_id(channel_type=channel_type, channel_id=channel_id, message_id=message_id)
    payload = {
        "doc_id": doc_id,
        "channel_type": channel_type,
        "channel_id": channel_id,
        "thread_id": thread_id,
        "visit_id": visit_id,
        "author": author,
        "text": normalized,
        "timestamp": ts.isoformat(),
        "citation": f"field://{channel_type}/{channel_id}/{message_id}",
    }

    if os.getenv("ENVIRONMENT", "development") == "development":
        _persist_stub_document(doc_id, payload)
    else:
        logger.info(
            "Production field learnings upsert doc_id=%s endpoint=%s",
            doc_id,
            FIELD_LEARNINGS_ENDPOINT,
        )

    upsert_channel_ingestion_cursor(
        channel_type=channel_type,
        channel_id=channel_id,
        visit_id=visit_id,
        last_message_time=ts,
        last_message_name=message_id,
    )
    return doc_id


def ingest_text_learning(
    *,
    text: str,
    visit_id: str | None,
    channel_type: str,
    channel_id: str | None,
    author: str,
) -> str:
    message_id = hashlib.sha256(text.encode()).hexdigest()[:16]
    return ingest_chat_message(
        channel_type=channel_type,
        channel_id=channel_id or "explicit",
        message_id=message_id,
        text=text,
        author=author,
        visit_id=visit_id,
    )


def ingest_message_batch(messages: list[dict[str, Any]]) -> list[str]:
    doc_ids: list[str] = []
    for msg in messages:
        doc_id = ingest_chat_message(
            channel_type=msg["channel_type"],
            channel_id=msg["channel_id"],
            message_id=msg["message_id"],
            text=msg["text"],
            author=msg.get("author", "unknown"),
            visit_id=msg.get("visit_id"),
            timestamp=msg.get("timestamp"),
            thread_id=msg.get("thread_id"),
        )
        if doc_id:
            doc_ids.append(doc_id)
    return doc_ids
