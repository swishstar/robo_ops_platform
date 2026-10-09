"""
Field learnings ingestion — auto-index channel messages into the field_learnings corpus.

In development, writes JSON stubs locally. In production, upserts documents to
Vertex AI Search (Discovery Engine) data store `field-learnings`.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from database import upsert_channel_ingestion_cursor

logger = logging.getLogger(__name__)

FIELD_LEARNINGS_ENDPOINT = os.getenv(
    "FIELD_LEARNINGS_SEARCH_ENDPOINT",
    "https://discoveryengine.googleapis.com/v1/projects/robo-reliance-ops/locations/global/"
    "collections/default_collection/engines/field-learnings/servingConfigs/default_search",
)
FIELD_LEARNINGS_STORE = Path(os.getenv("FIELD_LEARNINGS_STORE", "/tmp/field_learnings"))
FIELD_LEARNINGS_DATA_STORE = os.getenv("FIELD_LEARNINGS_DATA_STORE", "field-learnings")
FIELD_LEARNINGS_GCS_PREFIX = os.getenv(
    "FIELD_LEARNINGS_GCS_PREFIX",
    "gs://robo-reliance-ops-field-learnings",
)
GOOGLE_CLOUD_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT") or "robo-reliance-ops"


def _document_id(*, channel_type: str, channel_id: str, message_id: str) -> str:
    raw = f"{channel_type}:{channel_id}:{message_id}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _persist_stub_document(doc_id: str, payload: Dict[str, Any]) -> None:
    FIELD_LEARNINGS_STORE.mkdir(parents=True, exist_ok=True)
    path = FIELD_LEARNINGS_STORE / f"{doc_id}.json"
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def _documents_parent() -> str:
    return (
        f"projects/{GOOGLE_CLOUD_PROJECT}/locations/global/collections/default_collection/"
        f"dataStores/{FIELD_LEARNINGS_DATA_STORE}/branches/default_branch"
    )


def _markdown_body(payload: Dict[str, Any]) -> str:
    title = payload.get("title") or f"Field learning ({payload.get('channel_type', 'unknown')})"
    lines = [
        f"# {title}",
        "",
        payload.get("text", "").strip(),
        "",
        f"Citation: {payload.get('citation', '')}",
    ]
    if payload.get("visit_id"):
        lines.append(f"Visit: {payload['visit_id']}")
    if payload.get("author"):
        lines.append(f"Author: {payload['author']}")
    if payload.get("timestamp"):
        lines.append(f"Timestamp: {payload['timestamp']}")
    return "\n".join(lines) + "\n"


def _upsert_vertex_document(doc_id: str, payload: Dict[str, Any]) -> None:
    """Create-or-update an unstructured document in the field-learnings data store."""
    try:
        import google.auth
        import google.auth.transport.requests
        import httpx
    except ImportError as exc:
        raise RuntimeError("google-auth and httpx required for field learnings upsert") from exc

    credentials, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    request = google.auth.transport.requests.Request()
    credentials.refresh(request)
    token = getattr(credentials, "token", None)
    if not token:
        raise RuntimeError("Failed to obtain Google access token for Discovery Engine")

    body_text = _markdown_body(payload)
    raw_b64 = base64.b64encode(body_text.encode("utf-8")).decode("ascii")
    parent = _documents_parent()
    url = f"https://discoveryengine.googleapis.com/v1/{parent}/documents?documentId={doc_id}"

    document = {
        "id": doc_id,
        "structData": {
            "channel_type": payload.get("channel_type"),
            "channel_id": payload.get("channel_id"),
            "visit_id": payload.get("visit_id"),
            "author": payload.get("author"),
            "citation": payload.get("citation"),
            "timestamp": payload.get("timestamp"),
            "title": payload.get("title") or "",
        },
        "content": {
            "mimeType": "text/markdown",
            "rawBytes": raw_b64,
        },
    }

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "x-goog-user-project": GOOGLE_CLOUD_PROJECT,
    }

    with httpx.Client(timeout=30.0) as client:
        response = client.post(url, headers=headers, json=document)
        if response.status_code == 409:
            # Already exists — patch content
            patch_url = f"https://discoveryengine.googleapis.com/v1/{parent}/documents/{doc_id}"
            response = client.patch(
                patch_url,
                headers=headers,
                params={"updateMask": "content,structData"},
                json=document,
            )
        if response.status_code >= 400:
            logger.error(
                "Field learnings upsert failed (%s): %s",
                response.status_code,
                response.text[:500],
            )
            raise RuntimeError(
                f"Field learnings upsert error {response.status_code}: {response.text[:300]}"
            )


def ingest_chat_message(
    *,
    channel_type: str,
    channel_id: str,
    message_id: str,
    text: str,
    author: str,
    visit_id: Optional[str],
    timestamp: Optional[datetime] = None,
    thread_id: Optional[str] = None,
    title: Optional[str] = None,
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
        "title": title or f"Field learning — {channel_type}",
    }

    if os.getenv("ENVIRONMENT", "development") == "development":
        _persist_stub_document(doc_id, payload)
    else:
        logger.info(
            "Production field learnings upsert doc_id=%s data_store=%s",
            doc_id,
            FIELD_LEARNINGS_DATA_STORE,
        )
        try:
            _upsert_vertex_document(doc_id, payload)
        except Exception:
            logger.exception("Field learnings Vertex upsert failed for doc_id=%s", doc_id)
            # Still advance cursor so we do not tight-loop on poison messages.
            # Document can be recovered via GCS batch import later.

    upsert_channel_ingestion_cursor(
        channel_type=channel_type,
        channel_id=channel_id,
        visit_id=visit_id,
        last_message_time=ts,
        last_message_name=message_id,
    )
    return doc_id


def ingest_labor_finding(
    *,
    visit_id: str,
    labor_log_id: str,
    findings: str,
    technician_identity: str,
    location_string: Optional[str] = None,
) -> str:
    """Index extracted_findings from a labor_log into the field learnings corpus."""
    normalized = (findings or "").strip()
    if not normalized:
        return ""
    title = "Visit findings"
    if location_string:
        title = f"Visit findings — {location_string}"
    return ingest_chat_message(
        channel_type="labor_log",
        channel_id=visit_id,
        message_id=labor_log_id,
        text=normalized,
        author=technician_identity or "technician",
        visit_id=visit_id,
        title=title,
    )


def ingest_text_learning(
    *,
    text: str,
    visit_id: Optional[str],
    channel_type: str,
    channel_id: Optional[str],
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


def ingest_message_batch(messages: List[Dict[str, Any]]) -> List[str]:
    doc_ids: List[str] = []
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
            title=msg.get("title"),
        )
        if doc_id:
            doc_ids.append(doc_id)
    return doc_ids
