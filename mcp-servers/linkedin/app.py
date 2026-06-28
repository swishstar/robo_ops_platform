"""
LinkedIn MCP adapter — local mock implementation (Phase 4).

Receives JSON-RPC 2.0 envelopes from the orchestrator, logs transaction receipts
to stdout, and returns schema-compliant staged-post payloads.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from pydantic import BaseModel, Field, ValidationError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [MCP:linkedin] %(levelname)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("mcp.linkedin")

app = FastAPI(title="LinkedIn MCP Adapter", version="1.0.0")

SUPPORTED_METHODS = frozenset({"linkedin.stage_post"})


class JsonRpcRequest(BaseModel):
    jsonrpc: str = Field(default="2.0")
    id: str | int | None = None
    method: str
    params: dict[str, Any] = Field(default_factory=dict)


class StagePostParams(BaseModel):
    visit_id: str
    location_string: str = Field(..., min_length=3)
    summary_text: str = Field(..., min_length=8)
    media_urls: list[str] = Field(default_factory=list)


def _error_response(
    request_id: str | int | None,
    code: int,
    message: str,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}
    if data:
        payload["error"]["data"] = data
    return payload


def _success_response(request_id: str | int | None, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _log_receipt(method: str, params: dict[str, Any], result: dict[str, Any]) -> None:
    logger.info(
        "RECEIPT method=%s visit_id=%s receipt_id=%s status=%s post_urn=%s",
        method,
        params.get("visit_id"),
        result.get("receipt_id"),
        result.get("status"),
        result.get("post_urn"),
    )
    logger.info("RECEIPT_DETAIL params=%s result=%s", params, result)


def handle_stage_post(params: dict[str, Any]) -> dict[str, Any]:
    validated = StagePostParams.model_validate(params)
    receipt_id = f"LI-STG-{uuid4().hex[:12].upper()}"
    post_urn = f"urn:li:share:{uuid4()}"
    now = datetime.now(timezone.utc).isoformat()

    return {
        "receipt_id": receipt_id,
        "status": "staged",
        "adapter": "linkedin_marketing_mock",
        "method": "linkedin.stage_post",
        "post_urn": post_urn,
        "visit_id": validated.visit_id,
        "location_string": validated.location_string,
        "summary_text": validated.summary_text,
        "post_preview": validated.summary_text[:280],
        "media_urls": validated.media_urls,
        "visibility": "ORGANIZATION",
        "staged_at": now,
        "publish_state": "awaiting_manual_publish",
    }


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "service": "mcp_linkedin",
        "status": "ready",
        "port": 9002,
        "supported_methods": sorted(SUPPORTED_METHODS),
    }


@app.post("/jsonrpc")
async def jsonrpc_endpoint(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except Exception:
        return _error_response(None, -32700, "Parse error: request body must be valid JSON")

    if not isinstance(body, dict):
        return _error_response(None, -32600, "Invalid Request: envelope must be a JSON object")

    request_id = body.get("id")

    try:
        envelope = JsonRpcRequest.model_validate(body)
    except ValidationError as exc:
        return _error_response(request_id, -32600, f"Invalid Request: {exc.errors()[0]['msg']}")

    if envelope.jsonrpc != "2.0":
        return _error_response(request_id, -32600, "Invalid Request: jsonrpc must be '2.0'")

    if envelope.method not in SUPPORTED_METHODS:
        return _error_response(
            request_id,
            -32601,
            f"Method not found: {envelope.method}",
            data={"supported_methods": sorted(SUPPORTED_METHODS)},
        )

    logger.info("INBOUND method=%s id=%s params=%s", envelope.method, request_id, envelope.params)

    try:
        result = handle_stage_post(envelope.params)
    except ValidationError as exc:
        return _error_response(
            request_id,
            -32602,
            "Invalid params",
            data={"validation_errors": exc.errors()},
        )

    _log_receipt(envelope.method, envelope.params, result)
    return _success_response(request_id, result)
