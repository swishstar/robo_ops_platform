"""
QuickBooks Online MCP adapter — local mock implementation (Phase 4).

Receives JSON-RPC 2.0 envelopes from the orchestrator, logs transaction receipts
to stdout, and returns schema-compliant mock payloads.
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
    format="%(asctime)s [MCP:quickbooks] %(levelname)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("mcp.quickbooks")

app = FastAPI(title="QuickBooks MCP Adapter", version="1.0.0")

SUPPORTED_METHODS = frozenset({"quickbooks.create_invoice", "quickbooks.record_payout"})


class JsonRpcRequest(BaseModel):
    jsonrpc: str = Field(default="2.0")
    id: str | int | None = None
    method: str
    params: dict[str, Any] = Field(default_factory=dict)


class CreateInvoiceParams(BaseModel):
    visit_id: str
    ledger_id: str
    invoice_cents: int = Field(..., ge=0)
    calculated_hours: float = Field(..., gt=0)
    customer_reference: str = Field(..., min_length=1)


class RecordPayoutParams(BaseModel):
    visit_id: str
    ledger_id: str
    payout_cents: int = Field(..., ge=0)
    technician_identity: str = Field(..., min_length=3)


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
        "RECEIPT method=%s visit_id=%s ledger_id=%s receipt_id=%s status=%s",
        method,
        params.get("visit_id"),
        params.get("ledger_id"),
        result.get("receipt_id"),
        result.get("status"),
    )
    logger.info("RECEIPT_DETAIL params=%s result=%s", params, result)


def handle_create_invoice(params: dict[str, Any]) -> dict[str, Any]:
    validated = CreateInvoiceParams.model_validate(params)
    receipt_id = f"QBO-INV-{uuid4().hex[:12].upper()}"
    invoice_reference = f"INV-{validated.visit_id[:8].upper()}-{validated.ledger_id[:4].upper()}"
    now = datetime.now(timezone.utc).isoformat()

    return {
        "receipt_id": receipt_id,
        "status": "posted",
        "adapter": "quickbooks_online_mock",
        "method": "quickbooks.create_invoice",
        "invoice_reference": invoice_reference,
        "qbo_invoice_id": receipt_id,
        "visit_id": validated.visit_id,
        "ledger_id": validated.ledger_id,
        "customer_reference": validated.customer_reference,
        "invoice_cents": validated.invoice_cents,
        "calculated_hours": validated.calculated_hours,
        "currency": "USD",
        "posted_at": now,
        "line_items": [
            {
                "description": f"Field service labor ({validated.calculated_hours} hrs)",
                "amount_cents": validated.invoice_cents,
                "quantity": validated.calculated_hours,
                "unit_price_cents": int(validated.invoice_cents / validated.calculated_hours),
            }
        ],
    }


def handle_record_payout(params: dict[str, Any]) -> dict[str, Any]:
    validated = RecordPayoutParams.model_validate(params)
    receipt_id = f"QBO-PAY-{uuid4().hex[:12].upper()}"
    now = datetime.now(timezone.utc).isoformat()

    return {
        "receipt_id": receipt_id,
        "status": "recorded",
        "adapter": "quickbooks_online_mock",
        "method": "quickbooks.record_payout",
        "payout_reference": f"PAY-{validated.visit_id[:8].upper()}",
        "visit_id": validated.visit_id,
        "ledger_id": validated.ledger_id,
        "technician_identity": validated.technician_identity,
        "payout_cents": validated.payout_cents,
        "currency": "USD",
        "recorded_at": now,
    }


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "service": "mcp_quickbooks",
        "status": "ready",
        "port": 9001,
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
        if envelope.method == "quickbooks.create_invoice":
            result = handle_create_invoice(envelope.params)
        else:
            result = handle_record_payout(envelope.params)
    except ValidationError as exc:
        return _error_response(
            request_id,
            -32602,
            "Invalid params",
            data={"validation_errors": exc.errors()},
        )

    _log_receipt(envelope.method, envelope.params, result)
    return _success_response(request_id, result)
