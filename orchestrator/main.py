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
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, EmailStr, Field, field_validator

from agent_def import process_visit_signoff, tech_support_agent
from database import (
    close_async_pool,
    close_sync_pool,
    create_visit_from_slack,
    init_async_pool,
    init_sync_pool,
)

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
