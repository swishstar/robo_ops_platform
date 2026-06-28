"""
HTTP JSON-RPC client for remote MCP adapter services (QuickBooks, LinkedIn).

All external mutations flow through these wrappers after deterministic Python
validation in FastAPI routes or ADK tool handlers.
"""

from __future__ import annotations

import logging
import os
from typing import Any
from uuid import uuid4

import httpx

logger = logging.getLogger(__name__)

MCP_QUICKBOOKS_ENDPOINT = os.getenv("MCP_QUICKBOOKS_ENDPOINT", "http://localhost:9001")
MCP_LINKEDIN_ENDPOINT = os.getenv("MCP_LINKEDIN_ENDPOINT", "http://localhost:9002")
DEFAULT_TIMEOUT_SECONDS = float(os.getenv("MCP_HTTP_TIMEOUT_SECONDS", "30"))
MCP_USE_IDENTITY_TOKEN = os.getenv("MCP_USE_IDENTITY_TOKEN", "false").lower() == "true"


def _identity_token(audience: str) -> str | None:
    """Fetch a Google ID token for Cloud Run service-to-service calls."""
    try:
        import google.auth.transport.requests
        import google.oauth2.id_token

        request = google.auth.transport.requests.Request()
        return google.oauth2.id_token.fetch_id_token(request, audience)
    except Exception as exc:
        logger.error("Failed to fetch identity token for audience %s: %s", audience, exc)
        return None


class MCPClientError(Exception):
    """Raised when an MCP JSON-RPC call fails or returns an error object."""

    def __init__(self, service: str, message: str, *, payload: dict[str, Any] | None = None):
        super().__init__(f"[{service}] {message}")
        self.service = service
        self.payload = payload or {}


class MCPJsonRpcClient:
    """Standard JSON-RPC 2.0 over HTTP wrapper for Inner Loop MCP modules."""

    def __init__(self, base_url: str, service_name: str, timeout: float = DEFAULT_TIMEOUT_SECONDS):
        self.base_url = base_url.rstrip("/")
        self.service_name = service_name
        self.timeout = timeout

    async def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        request_id = str(uuid4())
        envelope: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params or {},
        }
        url = f"{self.base_url}/jsonrpc"
        logger.info("MCP outbound %s -> %s params=%s", self.service_name, method, params)

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if MCP_USE_IDENTITY_TOKEN:
            token = _identity_token(self.base_url)
            if token:
                headers["Authorization"] = f"Bearer {token}"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(url, json=envelope, headers=headers)
            response.raise_for_status()
            payload = response.json()

        if "error" in payload:
            raise MCPClientError(
                self.service_name,
                payload["error"].get("message", "Unknown JSON-RPC error"),
                payload=payload,
            )

        result = payload.get("result")
        if not isinstance(result, dict):
            raise MCPClientError(
                self.service_name,
                "MCP response missing result object",
                payload=payload,
            )

        logger.info("MCP receipt %s <- %s", self.service_name, result.get("receipt_id", request_id))
        return result


class QuickBooksMCPClient(MCPJsonRpcClient):
    """QuickBooks Online invoice + payout adapter."""

    def __init__(self, base_url: str | None = None):
        super().__init__(base_url or MCP_QUICKBOOKS_ENDPOINT, "quickbooks")

    async def create_invoice(
        self,
        *,
        visit_id: str,
        ledger_id: str,
        invoice_cents: int,
        calculated_hours: float,
        customer_reference: str,
    ) -> dict[str, Any]:
        return await self.call(
            "quickbooks.create_invoice",
            {
                "visit_id": visit_id,
                "ledger_id": ledger_id,
                "invoice_cents": invoice_cents,
                "calculated_hours": calculated_hours,
                "customer_reference": customer_reference,
            },
        )

    async def record_technician_payout(
        self,
        *,
        visit_id: str,
        ledger_id: str,
        payout_cents: int,
        technician_identity: str,
    ) -> dict[str, Any]:
        return await self.call(
            "quickbooks.record_payout",
            {
                "visit_id": visit_id,
                "ledger_id": ledger_id,
                "payout_cents": payout_cents,
                "technician_identity": technician_identity,
            },
        )


class LinkedInMCPClient(MCPJsonRpcClient):
    """LinkedIn social post staging adapter."""

    def __init__(self, base_url: str | None = None):
        super().__init__(base_url or MCP_LINKEDIN_ENDPOINT, "linkedin")

    async def stage_completion_post(
        self,
        *,
        visit_id: str,
        location_string: str,
        summary_text: str,
        media_urls: list[str] | None = None,
    ) -> dict[str, Any]:
        return await self.call(
            "linkedin.stage_post",
            {
                "visit_id": visit_id,
                "location_string": location_string,
                "summary_text": summary_text,
                "media_urls": media_urls or [],
            },
        )


quickbooks_client = QuickBooksMCPClient()
linkedin_client = LinkedInMCPClient()
