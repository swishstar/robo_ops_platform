"""
FastAPI orchestration layer for the Robo Reliance Inner Loop Platform.

Webhook ingestion routes validate payloads deterministically before any database
mutation or external MCP call occurs.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, EmailStr, Field, field_validator

from agent_def import process_visit_signoff, tech_support_agent
from database import (
    close_async_pool,
    close_sync_pool,
    commit_finance_approval_success,
    commit_finance_rejection,
    create_visit_from_slack,
    get_platform_configs,
    init_async_pool,
    init_sync_pool,
    load_finance_approval_bundle,
)
from mcp_client import MCPClientError, linkedin_client, quickbooks_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("inner_loop.orchestrator")


class PointOfContact(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)
    phone: str = Field(..., min_length=7, max_length=32)
    email: EmailStr


class SlackWebhookPayload(BaseModel):
    slack_channel_id: str = Field(..., min_length=3, max_length=100)
    location_string: str = Field(..., min_length=3)
    metadata_poc: PointOfContact
    technician_identity: str | None = Field(default=None, max_length=255)
    trigger_signoff_simulation: bool = False
    clock_in: datetime | None = None
    clock_out: datetime | None = None
    findings: str | None = None

    @field_validator("slack_channel_id")
    @classmethod
    def validate_slack_channel(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned.startswith(("C", "G", "D")):
            raise ValueError("slack_channel_id must look like a Slack channel identifier.")
        return cleaned


class SignoffSimulationRequest(BaseModel):
    visit_id: str
    clock_in: datetime
    clock_out: datetime
    findings: str = Field(..., min_length=8)
    technician_identity: str = Field(default="field.tech@roboreliance.internal", min_length=3)


class HealthResponse(BaseModel):
    service: str
    environment: str
    database: str
    agent: str


class FinanceApprovePayload(BaseModel):
    approval_token: str = Field(..., min_length=16, max_length=128)
    operator_identity: str = Field(..., min_length=3, max_length=255)
    action: Literal["approve", "reject"] = "approve"
    rejection_reason: str | None = Field(default=None, max_length=500)

    @field_validator("approval_token")
    @classmethod
    def normalize_token(cls, value: str) -> str:
        return value.strip()


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_sync_pool()
    await init_async_pool()
    logger.info("Inner Loop orchestrator started (env=%s)", os.getenv("ENVIRONMENT", "development"))
    yield
    await close_async_pool()
    close_sync_pool()
    logger.info("Inner Loop orchestrator shutdown complete")


app = FastAPI(
    title="Robo Reliance Inner Loop Orchestrator",
    description="ADK-powered field operations runtime with deterministic validation gates.",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    return HealthResponse(
        service="inner_loop_orchestrator",
        environment=os.getenv("ENVIRONMENT", "development"),
        database="connected",
        agent=tech_support_agent.name,
    )


@app.get("/agent/metadata")
async def agent_metadata() -> dict[str, Any]:
    return {
        "agent_name": tech_support_agent.name,
        "model": getattr(tech_support_agent, "model", "gemini-2.0-pro"),
        "tools": [
            {"name": "lookup_technical_sop", "type": "deterministic_rag_gateway"},
            {"name": "process_visit_signoff", "type": "deterministic_ledger_writer"},
        ],
        "webhooks": [
            {"path": "/webhooks/slack", "type": "intake"},
            {"path": "/webhooks/finance-approve", "type": "hitl_finance_gateway"},
        ],
        "policy": "AI interprets and suggests; deterministic backend code validates and executes.",
    }


@app.post("/webhooks/slack")
async def slack_webhook(payload: SlackWebhookPayload) -> dict[str, Any]:
    """
    Slack intake webhook.

    Validates payload shape, persists an initiated visit row, and returns a
    simulated Google Chat Spaces provisioning receipt for local composition.
    """
    google_space_token = f"spaces/{uuid4()}"
    room_display_name = f"RR Visit — {payload.location_string[:64]}"

    visit = create_visit_from_slack(
        slack_channel_id=payload.slack_channel_id,
        location_string=payload.location_string.strip(),
        metadata_poc=payload.metadata_poc.model_dump(),
        google_space_id=google_space_token,
    )

    simulation: dict[str, Any] = {
        "status": "space_provisioned_simulation",
        "visit_id": str(visit.visit_id),
        "google_chat": {
            "space_resource_name": visit.google_space_id,
            "room_token": google_space_token,
            "display_name": room_display_name,
            "membership_policy": "field_ops_private",
            "provisioned_at": datetime.now(timezone.utc).isoformat(),
        },
        "visit_state": visit.current_state,
        "slack_channel_id": visit.slack_channel_id,
        "location_string": visit.location_string,
    }

    if payload.trigger_signoff_simulation:
        if not payload.clock_in or not payload.clock_out or not payload.findings:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "trigger_signoff_simulation requires clock_in, clock_out, and findings fields."
                ),
            )
        signoff = process_visit_signoff(
            visit_id=str(visit.visit_id),
            clock_in_str=payload.clock_in.astimezone(timezone.utc).isoformat(),
            clock_out_str=payload.clock_out.astimezone(timezone.utc).isoformat(),
            text_findings=payload.findings,
            technician_identity=payload.technician_identity or "field.tech@roboreliance.internal",
        )
        simulation["signoff_receipt"] = signoff

    logger.info(
        "Slack intake persisted visit_id=%s space=%s",
        visit.visit_id,
        visit.google_space_id,
    )
    return simulation


@app.post("/tools/process-visit-signoff")
async def direct_signoff_tool(request: SignoffSimulationRequest) -> dict[str, Any]:
    """
    Deterministic HTTP bridge for integration tests.

    Bypasses the LLM and invokes the hardened sign-off tool directly.
    """
    return process_visit_signoff(
        visit_id=request.visit_id,
        clock_in_str=request.clock_in.astimezone(timezone.utc).isoformat(),
        clock_out_str=request.clock_out.astimezone(timezone.utc).isoformat(),
        text_findings=request.findings,
        technician_identity=request.technician_identity,
    )


@app.post("/webhooks/finance-approve")
async def finance_approve_webhook(payload: FinanceApprovePayload) -> dict[str, Any]:
    """
    Human-in-the-loop finance gateway.

    Validates the approval token, reads platform configs from Postgres, invokes
    QuickBooks and LinkedIn MCP adapters on approve, then commits ledger state.
    """
    configs = get_platform_configs(["finance", "quickbooks", "linkedin"])
    finance_cfg = configs.get("finance", {})
    if finance_cfg.get("require_operator_identity") and not payload.operator_identity.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="operator_identity is required by platform finance policy.",
        )

    try:
        bundle = load_finance_approval_bundle(payload.approval_token)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    if bundle is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Approval token not found.",
        )

    if payload.action == "reject":
        if not payload.rejection_reason or len(payload.rejection_reason.strip()) < 5:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="rejection_reason is required when action is reject.",
            )
        result = commit_finance_rejection(
            approval_token=payload.approval_token,
            operator_identity=payload.operator_identity.strip(),
            rejection_reason=payload.rejection_reason.strip(),
        )
        if result.status != "success":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=result.message)
        return {
            "status": "rejected",
            "visit_id": result.visit_id,
            "ledger_id": result.ledger_id,
            "visit_state": result.visit_state,
            "approval_state": result.approval_state,
        }

    qbo_cfg = configs.get("quickbooks", {})
    if not qbo_cfg.get("enabled", True):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="QuickBooks integration is disabled in platform_configs.",
        )

    customer_reference = qbo_cfg.get("customer_reference_default", "RR-GENERAL-CUSTOMER")
    mcp_receipts: dict[str, Any] = {}

    try:
        invoice_receipt = await quickbooks_client.create_invoice(
            visit_id=bundle.visit_id,
            ledger_id=bundle.ledger_id,
            invoice_cents=bundle.invoice_cents,
            calculated_hours=bundle.calculated_hours,
            customer_reference=customer_reference,
        )
        mcp_receipts["quickbooks_invoice"] = invoice_receipt

        payout_receipt = await quickbooks_client.record_technician_payout(
            visit_id=bundle.visit_id,
            ledger_id=bundle.ledger_id,
            payout_cents=bundle.payout_cents,
            technician_identity=bundle.technician_identity,
        )
        mcp_receipts["quickbooks_payout"] = payout_receipt

        linkedin_cfg = configs.get("linkedin", {})
        if linkedin_cfg.get("post_enabled", True):
            summary_prefix = linkedin_cfg.get("summary_prefix", "Robo Reliance Field Ops:")
            summary_text = (
                f"{summary_prefix} Completed service visit at {bundle.location_string}. "
                f"{bundle.extracted_findings[:280]}"
            )
            linkedin_receipt = await linkedin_client.stage_completion_post(
                visit_id=bundle.visit_id,
                location_string=bundle.location_string,
                summary_text=summary_text,
            )
            mcp_receipts["linkedin_post"] = linkedin_receipt
    except MCPClientError as exc:
        logger.error("MCP execution failed during finance approval: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    qbo_invoice_reference = (
        invoice_receipt.get("invoice_reference")
        or invoice_receipt.get("qbo_invoice_id")
        or invoice_receipt.get("receipt_id")
        or f"QBO-SIM-{bundle.ledger_id[:8]}"
    )

    commit_result = commit_finance_approval_success(
        approval_token=payload.approval_token,
        operator_identity=payload.operator_identity.strip(),
        qbo_invoice_reference=str(qbo_invoice_reference),
        mcp_receipts=mcp_receipts,
    )
    if commit_result.status != "success":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=commit_result.message,
        )

    logger.info(
        "Finance approval committed visit_id=%s ledger_id=%s qbo_ref=%s",
        commit_result.visit_id,
        commit_result.ledger_id,
        commit_result.qbo_invoice_reference,
    )
    return {
        "status": "approved",
        "visit_id": commit_result.visit_id,
        "ledger_id": commit_result.ledger_id,
        "visit_state": commit_result.visit_state,
        "approval_state": commit_result.approval_state,
        "qbo_invoice_reference": commit_result.qbo_invoice_reference,
        "mcp_receipts": mcp_receipts,
        "operator_identity": payload.operator_identity.strip(),
    }
