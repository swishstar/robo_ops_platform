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
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

from agent_def import process_visit_signoff, tech_support_agent
from api_v1 import router as api_v1_router
from chat_webhook import handle_google_chat_event
from database import (
    close_async_pool,
    close_sync_pool,
    init_async_pool,
    init_sync_pool,
)
from finance_service import execute_finance_approval
from slack_events import handle_slack_event

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("inner_loop.orchestrator")


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


class FinanceWebhookPayload(BaseModel):
    approval_token: str = Field(..., min_length=16, max_length=128)
    operator_identity: str = Field(..., min_length=3, max_length=255)
    action: str = "approve"
    rejection_reason: Optional[str] = Field(default=None, max_length=500)

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
    version="1.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:3000").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_v1_router)


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
            {"name": "lookup_field_learnings", "type": "field_learnings_rag"},
            {"name": "get_visit_context", "type": "deterministic_read"},
            {"name": "clock_in_visit", "type": "deterministic_labor_writer"},
            {"name": "process_visit_signoff", "type": "deterministic_ledger_writer"},
        ],
        "webhooks": [
            {"path": "/webhooks/slack", "type": "slack_channel_agent"},
            {"path": "/webhooks/google-chat", "type": "google_chat_channel_agent"},
            {"path": "/webhooks/finance", "type": "hitl_finance_gateway"},
        ],
        "api": [
            {"path": "/api/v1/visits", "type": "ops_web_app"},
            {"path": "/api/v1/finance/ledgers", "type": "finance_table"},
            {"path": "/api/v1/web-chat/message", "type": "embedded_web_chat"},
        ],
        "policy": "AI interprets and suggests; deterministic backend code validates and executes.",
    }


@app.post("/webhooks/slack")
async def slack_webhook(payload: dict[str, Any]) -> dict[str, Any]:
    """Slack Events API — channel agent for client/external technical discussion."""
    return handle_slack_event(payload)


@app.post("/webhooks/google-chat")
async def google_chat_webhook(payload: dict[str, Any]) -> dict[str, Any]:
    """Google Chat app — internal visit spaces and invitable agent."""
    return handle_google_chat_event(payload)


@app.post("/webhooks/finance")
async def finance_webhook(payload: FinanceWebhookPayload) -> dict[str, Any]:
    """Human-in-the-loop finance gateway."""
    action = payload.action if payload.action in ("approve", "reject") else "approve"
    return await execute_finance_approval(
        approval_token=payload.approval_token,
        operator_identity=payload.operator_identity,
        action=action,  # type: ignore[arg-type]
        rejection_reason=payload.rejection_reason,
    )


@app.post("/tools/process-visit-signoff")
async def direct_signoff_tool(request: SignoffSimulationRequest) -> dict[str, Any]:
    """Deterministic HTTP bridge for integration tests."""
    return process_visit_signoff(
        visit_id=request.visit_id,
        clock_in_str=request.clock_in.astimezone(timezone.utc).isoformat(),
        clock_out_str=request.clock_out.astimezone(timezone.utc).isoformat(),
        text_findings=request.findings,
        technician_identity=request.technician_identity,
    )
