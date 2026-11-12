"""
Authenticated REST API v1 for the Ops & Finance web app and embedded Web Chat.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, EmailStr, Field

from agent_def import process_visit_signoff
from agent_runner import ChannelContext, handle_agent_turn
from auth import AuthenticatedUser, get_current_user, require_admin, require_finance_manager
from client_corpus import list_known_clients, normalize_client_id
from database import (
    clock_in_transaction,
    create_visit,
    format_technician_identity,
    get_finance_ledger_detail,
    get_labor_log,
    get_visit_detail,
    list_finance_ledgers,
    list_pending_finance,
    list_technician_rates,
    list_timesheet_rows,
    list_visits,
    record_timesheet_entry,
    touch_web_chat_session,
    update_labor_payment_flags,
    update_visit,
    upsert_technician_rate,
)

router = APIRouter(prefix="/api/v1", tags=["api-v1"])


class PointOfContact(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)
    phone: str = Field(..., min_length=7, max_length=32)
    email: EmailStr


class CreateVisitRequest(BaseModel):
    location_string: str = Field(..., min_length=3)
    metadata_poc: PointOfContact
    client_id: Optional[str] = Field(
        default=None,
        max_length=64,
        description="Client key selecting the SOP corpus (e.g. chef).",
    )
    work_order_number: Optional[str] = Field(
        default=None,
        max_length=120,
        description="Client/internal job id (e.g. RoboJob_00126).",
    )
    slack_channel_id: Optional[str] = Field(default=None, max_length=100)


class UpdateVisitRequest(BaseModel):
    location_string: Optional[str] = Field(default=None, min_length=3)
    metadata_poc: Optional[PointOfContact] = None
    client_id: Optional[str] = Field(default=None, max_length=64)
    work_order_number: Optional[str] = Field(default=None, max_length=120)
    slack_channel_id: Optional[str] = Field(default=None, max_length=100)
    clear_slack_channel: bool = False


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


class CreateTimesheetRequest(BaseModel):
    visit_id: str = Field(..., min_length=8)
    technician_identity: Optional[str] = Field(default=None, max_length=255)
    technician_name: Optional[str] = Field(default=None, max_length=120)
    clock_in: datetime
    clock_out: datetime
    findings: str = Field(default="", max_length=8000)
    timesheet: Optional[TimesheetMetadata] = None
    explicit_amount_cents: Optional[int] = Field(default=None, ge=0)
    paid_to_contractor: Optional[bool] = None
    billed_to_client: Optional[bool] = None
    paid_by_client: Optional[bool] = None


class UpdateTimesheetFlagsRequest(BaseModel):
    paid_to_contractor: Optional[bool] = None
    billed_to_client: Optional[bool] = None
    paid_by_client: Optional[bool] = None


class UpsertTechnicianRateRequest(BaseModel):
    technician_email: EmailStr
    technician_name: Optional[str] = Field(default=None, max_length=255)
    payout_cents_per_hour: int = Field(..., ge=0, le=1_000_000)
    invoice_cents_per_hour: int = Field(..., ge=0, le=1_000_000)


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
        if isinstance(value, Decimal):
            out[key] = float(value)
        elif hasattr(value, "isoformat"):
            out[key] = value.isoformat()
        elif hasattr(value, "hex"):
            out[key] = str(value)
        else:
            out[key] = value
    return out


def _blank(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _parse_day(value: Optional[str]) -> Optional[datetime]:
    cleaned = _blank(value)
    if cleaned is None:
        return None
    return datetime.strptime(cleaned, "%Y-%m-%d")


def _validate_submitted_timesheet(ts: TimesheetMetadata) -> None:
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


def _timesheet_identity(
    user: AuthenticatedUser,
    technician_identity: Optional[str],
    technician_name: Optional[str],
) -> str:
    """Technicians always log their own email. Admins and finance may name someone else."""
    if user.role == "technician":
        return user.email
    raw = _blank(technician_identity) or user.email
    name = _blank(technician_name)
    if name and "<" not in raw:
        return format_technician_identity(raw, name)
    return raw


@router.get("/clients")
async def api_list_clients(
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Known clients for visit intake + SOP corpus routing."""
    del user  # auth required; payload is not user-scoped
    return list_known_clients()


@router.post("/visits")
async def api_create_visit(
    body: CreateVisitRequest,
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        client_id = normalize_client_id(body.client_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    if client_id is None:
        client_id = list_known_clients().get("default_client_id") or "chef"

    visit = create_visit(
        location_string=body.location_string.strip(),
        metadata_poc=body.metadata_poc.model_dump(),
        slack_channel_id=body.slack_channel_id,
        client_id=client_id,
        work_order_number=body.work_order_number,
        source="web_app",
    )
    return {
        "status": "visit_created",
        "visit_id": str(visit.visit_id),
        "google_space_id": visit.google_space_id,
        "slack_channel_id": visit.slack_channel_id,
        "location_string": visit.location_string,
        "client_id": visit.client_id,
        "work_order_number": visit.work_order_number,
        "visit_state": visit.current_state,
    }


@router.get("/visits")
async def api_list_visits(
    state: Optional[str] = Query(default=None),
    technician: Optional[str] = Query(
        default=None,
        description="Optional filter; substring match on labor_logs.technician_identity.",
    ),
    include_completed: bool = Query(default=False),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    # Full list: admins only. Technicians (and other roles) see their own labor rows.
    effective_technician = technician
    if user.role != "admin" and not effective_technician:
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
    if user.role != "admin":
        tech = (user.email or "").lower()
        logs = detail.get("labor_logs") or []
        on_visit = any(
            tech
            and tech in str(log.get("technician_identity") or "").lower()
            for log in logs
        )
        if not on_visit and logs:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not assigned to this visit.")
        # Initiated visits with no labor yet: allow creator-style access for techs
        # so they can clock in after opening a new request they created.
    return _serialize_row(detail)


@router.patch("/visits/{visit_id}")
async def api_update_visit(
    visit_id: str,
    body: UpdateVisitRequest,
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    require_admin(user)
    client_id = body.client_id
    if client_id is not None:
        try:
            client_id = normalize_client_id(client_id)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    updated = update_visit(
        visit_id=visit_id,
        location_string=body.location_string,
        metadata_poc=body.metadata_poc.model_dump() if body.metadata_poc else None,
        client_id=client_id,
        work_order_number=body.work_order_number,
        slack_channel_id=body.slack_channel_id,
        clear_slack_channel=body.clear_slack_channel,
        actor_email=user.email,
    )
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Visit not found.")
    detail = get_visit_detail(visit_id)
    return _serialize_row(detail or updated)


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
        _validate_submitted_timesheet(body.timesheet)
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


@router.get("/timesheets")
async def api_list_timesheets(
    technician: Optional[str] = Query(default=None),
    client: Optional[str] = Query(default=None),
    work_order: Optional[str] = Query(default=None),
    date_from: Optional[str] = Query(default=None),
    date_to: Optional[str] = Query(default=None),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Admins and finance see every row. Technicians see their own."""
    if user.role == "technician":
        technician_filter: Optional[str] = user.email
    else:
        technician_filter = _blank(technician)
    try:
        start = _parse_day(date_from)
        end = _parse_day(date_to)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Dates must be YYYY-MM-DD.",
        ) from exc
    if start and end and end.date() < start.date():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="date_to is before date_from.",
        )
    limit = 1000
    rows = list_timesheet_rows(
        technician=technician_filter,
        client=_blank(client),
        work_order=_blank(work_order),
        date_from=start.date() if start else None,
        date_to=end.date() if end else None,
        limit=limit,
    )
    return {
        "timesheets": [_serialize_row(row) for row in rows],
        "truncated": len(rows) >= limit,
    }


@router.post("/timesheets")
async def api_create_timesheet(
    body: CreateTimesheetRequest,
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    if body.timesheet:
        _validate_submitted_timesheet(body.timesheet)
    identity = _timesheet_identity(user, body.technician_identity, body.technician_name)
    timesheet_payload = body.timesheet.model_dump(exclude_none=True) if body.timesheet else None
    # Payment progress is set by finance, not by the person logging hours.
    can_set_flags = user.role in {"finance_manager", "admin"}
    result = record_timesheet_entry(
        visit_id=body.visit_id.strip(),
        technician_identity=identity,
        clock_in=body.clock_in,
        clock_out=body.clock_out,
        findings=body.findings,
        timesheet_metadata=timesheet_payload,
        explicit_amount_cents=body.explicit_amount_cents,
        paid_to_contractor=body.paid_to_contractor if can_set_flags else None,
        billed_to_client=body.billed_to_client if can_set_flags else None,
        paid_by_client=body.paid_by_client if can_set_flags else None,
        actor_email=user.email,
    )
    if result.get("status") != "success":
        message = str(result.get("message") or "Timesheet rejected.")
        code = (
            status.HTTP_404_NOT_FOUND
            if "Unknown visit" in message
            else status.HTTP_422_UNPROCESSABLE_ENTITY
        )
        raise HTTPException(status_code=code, detail=message)
    return result


@router.patch("/timesheets/{log_id}")
async def api_update_timesheet_flags(
    log_id: str,
    body: UpdateTimesheetFlagsRequest,
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    require_finance_manager(user)
    existing = get_labor_log(log_id)
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Timesheet row not found.")
    updated = update_labor_payment_flags(
        log_id=log_id,
        paid_to_contractor=body.paid_to_contractor,
        billed_to_client=body.billed_to_client,
        paid_by_client=body.paid_by_client,
        actor_email=user.email,
    )
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Timesheet row not found.")
    return _serialize_row(updated)


@router.get("/finance/rates")
async def api_list_technician_rates(
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    require_finance_manager(user)
    return {"rates": [_serialize_row(row) for row in list_technician_rates()]}


@router.put("/finance/rates")
async def api_upsert_technician_rate(
    body: UpsertTechnicianRateRequest,
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    require_finance_manager(user)
    row = upsert_technician_rate(
        technician_email=str(body.technician_email),
        technician_name=body.technician_name,
        payout_cents_per_hour=body.payout_cents_per_hour,
        invoice_cents_per_hour=body.invoice_cents_per_hour,
    )
    return _serialize_row(row)


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
