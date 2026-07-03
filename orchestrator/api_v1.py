"""
Authenticated REST API v1 for the Ops & Finance web app and embedded Web Chat.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, EmailStr, Field

from agent_def import process_visit_signoff
from agent_runner import ChannelContext, handle_agent_turn
from auth import AuthenticatedUser, get_current_user, require_finance_manager
from database import (
    clock_in_transaction,
    create_visit,
    get_finance_ledger_detail,
    get_visit_detail,
    list_finance_ledgers,
    list_pending_finance,
    list_visits,
    touch_web_chat_session,
)

router = APIRouter(prefix="/api/v1", tags=["api-v1"])


class PointOfContact(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)
    phone: str = Field(..., min_length=7, max_length=32)
    email: EmailStr


class CreateVisitRequest(BaseModel):
    location_string: str = Field(..., min_length=3)
    metadata_poc: PointOfContact
    slack_channel_id: Optional[str] = Field(default=None, max_length=100)


class ClockInRequest(BaseModel):
    technician_identity: Optional[str] = None


CompletionStatus = Literal[
    "yes_fully_completed",
    "no_still_pending",
    "na_diagnosis_only",
]

FollowUpStatus = Literal[
    "no_complete",
    "yes_return_visit",
    "yes_remote_followup",
]

WorkCategory = Literal[
    "installation_setup",
    "troubleshooting_diagnosis",
    "repair_maintenance",
    "consultation_training",
    "preventative_check",
    "software_update_configuration",
]


class MediaFileRef(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    size_bytes: int = Field(..., ge=0, le=1_073_741_824)


class TimesheetMetadata(BaseModel):
    service_date: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    customer_site_name: Optional[str] = Field(default=None, max_length=255)
    work_order_number: Optional[str] = Field(default=None, max_length=120)
    invoice_number: Optional[str] = Field(default=None, max_length=120)
    completion_status: Optional[CompletionStatus] = None
    follow_up_status: Optional[FollowUpStatus] = None
    difficulty_rating: Optional[int] = Field(default=None, ge=1, le=5)
    work_categories: list[WorkCategory] = Field(default_factory=list, max_length=6)
    tools_equipment: Optional[str] = Field(default=None, max_length=2000)
    media_files: list[MediaFileRef] = Field(default_factory=list, max_length=10)
    attestation: bool = False


class SignoffRequest(BaseModel):
    clock_in: datetime
    clock_out: datetime
    findings: str = Field(..., min_length=8)
    technician_identity: Optional[str] = None
    timesheet: Optional[TimesheetMetadata] = None


class FinanceActionRequest(BaseModel):
    approval_token: str = Field(..., min_length=16)
    action: Literal["approve", "reject"] = "approve"
    rejection_reason: Optional[str] = Field(default=None, max_length=500)


class WebChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    visit_id: Optional[str] = None
    session_id: Optional[str] = None


def _serialize_row(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in row.items():
        if hasattr(value, "isoformat"):
            out[key] = value.isoformat()
        elif hasattr(value, "hex"):
            out[key] = str(value)
        else:
            out[key] = value
    return out


@router.post("/visits")
async def api_create_visit(
    body: CreateVisitRequest,
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    visit = create_visit(
        location_string=body.location_string.strip(),
        metadata_poc=body.metadata_poc.model_dump(),
        slack_channel_id=body.slack_channel_id,
        source="web_app",
    )
    return {
        "status": "visit_created",
        "visit_id": str(visit.visit_id),
        "google_space_id": visit.google_space_id,
        "slack_channel_id": visit.slack_channel_id,
        "location_string": visit.location_string,
        "visit_state": visit.current_state,
    }


@router.get("/visits")
async def api_list_visits(
    state: Optional[str] = Query(default=None),
    technician: Optional[str] = Query(default=None),
    include_completed: bool = Query(default=False),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    effective_technician = technician
    if user.role == "technician" and not technician:
        effective_technician = user.email
    rows = list_visits(
        state=state,
        technician=effective_technician,
        include_completed=include_completed,
    )
    return {"visits": [_serialize_row(r) for r in rows]}


@router.get("/visits/{visit_id}")
async def api_get_visit(
    visit_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    detail = get_visit_detail(visit_id)
    if not detail:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Visit not found.")
    return _serialize_row(detail)


@router.post("/visits/{visit_id}/clock-in")
async def api_clock_in(
    visit_id: str,
    body: ClockInRequest,
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    identity = body.technician_identity or user.email
    result = clock_in_transaction(visit_id=visit_id, technician_identity=identity)
    if result.get("status") != "success":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=result.get("message"))
    return result


@router.post("/visits/{visit_id}/signoff")
async def api_signoff(
    visit_id: str,
    body: SignoffRequest,
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    identity = body.technician_identity or user.email
    if body.timesheet:
        ts = body.timesheet
        if not ts.attestation:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Timesheet attestation is required before sign-off.",
            )
        if not ts.service_date:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Date of site visit is required.",
            )
        if not ts.completion_status:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Work completion status is required.",
            )
        if not ts.follow_up_status:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Follow-up status is required.",
            )
        if ts.difficulty_rating is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Difficulty rating is required.",
            )
        if not ts.work_categories:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Select at least one work category.",
            )
    timesheet_payload = body.timesheet.model_dump(exclude_none=True) if body.timesheet else None
    result = process_visit_signoff(
        visit_id=visit_id,
        clock_in_str=body.clock_in.isoformat(),
        clock_out_str=body.clock_out.isoformat(),
        text_findings=body.findings,
        technician_identity=identity,
        timesheet_metadata=timesheet_payload,
    )
    if result.get("status") != "success":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=result.get("message"))
    return result


@router.get("/finance/ledgers")
async def api_finance_ledgers(
    approval_state: Optional[str] = Query(default=None),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    require_finance_manager(user)
    rows = list_finance_ledgers(approval_state=approval_state)
    return {"ledgers": [_serialize_row(r) for r in rows]}


@router.get("/finance/pending")
async def api_finance_pending(
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    require_finance_manager(user)
    rows = list_pending_finance()
    return {"pending": [_serialize_row(r) for r in rows]}


@router.get("/finance/ledger/{ledger_id}")
async def api_finance_ledger(
    ledger_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    require_finance_manager(user)
    detail = get_finance_ledger_detail(ledger_id)
    if not detail:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ledger not found.")
    return _serialize_row(detail)


@router.post("/finance/approve")
async def api_finance_approve(
    body: FinanceActionRequest,
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    require_finance_manager(user)
    from finance_service import execute_finance_approval

    return await execute_finance_approval(
        approval_token=body.approval_token,
        operator_identity=user.email,
        action=body.action,
        rejection_reason=body.rejection_reason,
    )


@router.post("/web-chat/message")
async def api_web_chat_message(
    body: WebChatRequest,
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    session_id = body.session_id or f"web:{user.email}:{body.visit_id or 'global'}"
    touch_web_chat_session(
        session_id=session_id,
        user_identity=user.email,
        visit_id=body.visit_id,
    )
    context = ChannelContext(
        surface="web_chat",
        channel_id=session_id,
        visit_id=body.visit_id,
        user_identity=user.email,
    )
    turn = handle_agent_turn(body.message, context)
    return {
        "session_id": session_id,
        "reply": turn.reply_text,
        "citations": turn.citations,
        "tool_calls": turn.tool_calls,
    }
