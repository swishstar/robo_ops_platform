"""
Vertex AI Search (Discovery Engine) client for SOP / field-learnings RAG.
"""

from __future__ import annotations

import logging
import os
from typing import Any, List

import httpx

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = float(os.getenv("VERTEX_SEARCH_TIMEOUT_SECONDS", "20"))
DEFAULT_PAGE_SIZE = int(os.getenv("VERTEX_SEARCH_PAGE_SIZE", "5"))


def _access_token() -> str:
    """Fetch an access token via Application Default Credentials (Cloud Run SA)."""
    try:
        import google.auth
        import google.auth.transport.requests
    except ImportError as exc:
        raise RuntimeError("google-auth is required for Vertex AI Search") from exc

    credentials, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    request = google.auth.transport.requests.Request()
    credentials.refresh(request)
    token = getattr(credentials, "token", None)
    if not token:
        raise RuntimeError("Failed to obtain Google access token for Discovery Engine")
    return token


def _serving_config_path(endpoint_or_path: str) -> str:
    """
    Accept either a full HTTPS URL or a resource path ending in servingConfigs/*.
    """
    value = endpoint_or_path.strip().rstrip("/")
    if value.startswith("https://"):
        # https://discoveryengine.googleapis.com/v1/projects/.../servingConfigs/default_search
        marker = "/v1/"
        if marker not in value:
            raise ValueError(f"Unrecognized Discovery Engine URL: {endpoint_or_path}")
        return value.split(marker, 1)[1]
    if value.startswith("projects/"):
        return value
    raise ValueError(f"Unrecognized serving config: {endpoint_or_path}")


def _extract_snippets(document: dict[str, Any]) -> List[str]:
    derived = document.get("derivedStructData") or {}
    snippets: List[str] = []

    for snip in derived.get("snippets") or []:
        if isinstance(snip, dict):
            text = snip.get("snippet") or snip.get("text") or ""
            if text:
                snippets.append(str(text))
        elif isinstance(snip, str) and snip:
            snippets.append(snip)

    for answer in derived.get("extractive_answers") or derived.get("extractiveAnswers") or []:
        if isinstance(answer, dict):
            text = answer.get("content") or answer.get("text") or ""
            if text:
                snippets.append(str(text))

    for segment in derived.get("extractive_segments") or derived.get("extractiveSegments") or []:
        if isinstance(segment, dict):
            text = segment.get("content") or segment.get("text") or ""
            if text:
                snippets.append(str(text))

    content = document.get("content") or {}
    if not snippets and isinstance(content, dict):
        raw = content.get("rawBytes") or content.get("text")
        if isinstance(raw, str) and raw.strip():
            snippets.append(raw.strip()[:800])

    struct = document.get("structData") or {}
    if not snippets and isinstance(struct, dict):
        for key in ("text", "body", "content", "description"):
            if struct.get(key):
                snippets.append(str(struct[key])[:800])
                break

    return snippets


def _format_result(index: int, result: dict[str, Any]) -> str:
    document = result.get("document") or {}
    derived = document.get("derivedStructData") or {}
    title = (
        derived.get("title")
        or derived.get("link")
        or document.get("name")
        or result.get("id")
        or f"result-{index}"
    )
    link = derived.get("link") or derived.get("displayLink") or ""
    snippets = _extract_snippets(document)
    body = "\n".join(f"  {s}" for s in snippets[:3]) if snippets else "  (no snippet returned)"
    citation = f"\n  Citation: {link}" if link else ""
    return f"{index}. {title}\n{body}{citation}"


def search_vertex_ai(
    query: str,
    endpoint_or_path: str,
    *,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> str:
    """
    Call Discovery Engine `:search` and return a grounded text block for the agent.
    """
    serving_config = _serving_config_path(endpoint_or_path)
    url = f"https://discoveryengine.googleapis.com/v1/{serving_config}:search"
    token = _access_token()
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT") or ""

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    if project_id:
        headers["x-goog-user-project"] = project_id

    payload = {
        "query": query,
        "pageSize": page_size,
        "contentSearchSpec": {
            # Snippets work on Search Tier Standard; extractive answers need Enterprise.
            "snippetSpec": {"returnSnippet": True, "maxSnippetCount": 3},
        },
    }

    with httpx.Client(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
        response = client.post(url, headers=headers, json=payload)
        if response.status_code >= 400:
            logger.error(
                "Vertex AI Search failed (%s): %s",
                response.status_code,
                response.text[:500],
            )
            raise RuntimeError(
                f"Vertex AI Search error {response.status_code}: {response.text[:300]}"
            )
        body = response.json()

    results = body.get("results") or []
    if not results:
        summary = body.get("summary") or {}
        summary_text = summary.get("summaryText") if isinstance(summary, dict) else None
        if summary_text:
            return f"Vertex AI Search summary:\n{summary_text}"
        return (
            "No matching documents found in the Vertex AI Search index for this query. "
            "Confirm the SOP data store has been indexed."
        )

    lines = [f"SOP Context (Vertex AI Search) — query: {query}"]
    for i, result in enumerate(results[:page_size], start=1):
        if isinstance(result, dict):
            lines.append(_format_result(i, result))
    return "\n".join(lines)
