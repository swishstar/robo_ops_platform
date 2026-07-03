"""
PostgreSQL connection management for the Inner Loop orchestrator.

Provides both synchronous (psycopg2) and asynchronous (asyncpg) pools so
deterministic ADK tool code and FastAPI webhook handlers share one schema.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Iterator
from uuid import UUID, uuid4

import asyncpg
import psycopg2
import psycopg2.extras
from psycopg2.pool import ThreadedConnectionPool

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://engine_admin:development_vault_password@localhost:5432/roboreliance_local",
)

SYNC_POOL: ThreadedConnectionPool | None = None
ASYNC_POOL: asyncpg.Pool | None = None

CLIENT_INVOICE_CENTS_PER_HOUR = 15000
CONTRACTOR_PAYOUT_CENTS_PER_HOUR = 7500

DEFAULT_PLATFORM_CONFIGS: dict[str, dict[str, Any]] = {
    "finance": {"approval_token_ttl_hours": 72, "require_operator_identity": True},
    "quickbooks": {"enabled": True, "customer_reference_default": "RR-GENERAL-CUSTOMER"},
    "linkedin": {"post_enabled": True, "summary_prefix": "Robo Reliance Field Ops:"},
}


@dataclass(frozen=True)
class VisitRecord:
    visit_id: UUID
    slack_channel_id: str | None
    google_space_id: str
    location_string: str
    metadata_poc: dict[str, Any]
    current_state: str


@dataclass(frozen=True)
class SignoffResult:
    status: str
    visit_id: str
    calculated_hours: float | None = None
    invoice_cents: int | None = None
    payout_cents: int | None = None
    ledger_id: str | None = None
    labor_log_id: str | None = None
    approval_token: str | None = None
    message: str | None = None
    next_step: str | None = None


@dataclass(frozen=True)
class FinanceApprovalBundle:
    token_id: str
    approval_token: str
    ledger_id: str
    visit_id: str
    approval_state: str
    visit_state: str
    calculated_hours: float
    invoice_cents: int
    payout_cents: int
    location_string: str
    metadata_poc: dict[str, Any]
    technician_identity: str
    extracted_findings: str
    qbo_invoice_reference: str | None


@dataclass(frozen=True)
class FinanceApprovalCommitResult:
    status: str
    visit_id: str
    ledger_id: str
    visit_state: str
    approval_state: str
    qbo_invoice_reference: str | None = None
    message: str | None = None


def init_sync_pool(minconn: int = 1, maxconn: int = 10) -> ThreadedConnectionPool:
    global SYNC_POOL
    if SYNC_POOL is None:
        SYNC_POOL = ThreadedConnectionPool(minconn, maxconn, DATABASE_URL)
        logger.info("Initialized psycopg2 ThreadedConnectionPool")
    return SYNC_POOL


async def init_async_pool(min_size: int = 2, max_size: int = 10) -> asyncpg.Pool:
    global ASYNC_POOL
    if ASYNC_POOL is None:
        ASYNC_POOL = await asyncpg.create_pool(DATABASE_URL, min_size=min_size, max_size=max_size)
        logger.info("Initialized asyncpg connection pool")
    return ASYNC_POOL


async def close_async_pool() -> None:
    global ASYNC_POOL
    if ASYNC_POOL is not None:
        await ASYNC_POOL.close()
        ASYNC_POOL = None


def close_sync_pool() -> None:
    global SYNC_POOL
    if SYNC_POOL is not None:
        SYNC_POOL.closeall()
        SYNC_POOL = None


@contextmanager
def sync_connection() -> Iterator[psycopg2.extensions.connection]:
    pool = init_sync_pool()
    conn = pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


def _json(value: Any) -> str:
    return json.dumps(value, default=str)


def append_audit_trail(
    conn: psycopg2.extensions.connection,
    *,
    visit_id: UUID | str | None,
    execution_context: str,
    input_payload: dict[str, Any] | None,
    output_receipt: dict[str, Any] | None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO immutable_audit_trail
                (visit_id, execution_context, input_payload, output_receipt)
            VALUES (%s, %s, %s::jsonb, %s::jsonb)
            """,
            (
                str(visit_id) if visit_id else None,
                execution_context,
                _json(input_payload or {}),
                _json(output_receipt or {}),
            ),
        )


def get_platform_config(config_key: str) -> dict[str, Any]:
    """Load a platform configuration document from the database registry."""
    try:
        with sync_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT config_value
                    FROM platform_configs
                    WHERE config_key = %s
                    """,
                    (config_key,),
                )
                row = cur.fetchone()
                if row:
                    return dict(row["config_value"])
    except psycopg2.Error as exc:
        logger.warning("platform_configs lookup failed for %s: %s", config_key, exc)
    return dict(DEFAULT_PLATFORM_CONFIGS.get(config_key, {}))


def get_platform_configs(keys: list[str]) -> dict[str, dict[str, Any]]:
    return {key: get_platform_config(key) for key in keys}


def _issue_finance_approval_token(
    cur: psycopg2.extensions.cursor,
    *,
    ledger_id: UUID,
    visit_id: UUID,
    ttl_hours: int,
) -> str:
    approval_token = secrets.token_urlsafe(48)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)
    cur.execute(
        """
        INSERT INTO finance_approval_tokens
            (ledger_id, visit_id, approval_token, expires_at)
        VALUES (%s, %s, %s, %s)
        RETURNING approval_token
        """,
        (str(ledger_id), str(visit_id), approval_token, expires_at),
    )
    return cur.fetchone()["approval_token"]


def load_finance_approval_bundle(approval_token: str) -> FinanceApprovalBundle | None:
    """Fetch and validate the approval context for a HITL finance callback token."""
    token = approval_token.strip()
    if not token:
        return None

    with sync_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    fat.token_id,
                    fat.approval_token,
                    fat.consumed,
                    fat.expires_at,
                    fl.ledger_id,
                    fl.visit_id,
                    fl.approval_state,
                    fl.calculated_hours,
                    fl.invoice_cents,
                    fl.payout_cents,
                    fl.qbo_invoice_reference,
                    v.current_state::text AS visit_state,
                    v.location_string,
                    v.metadata_poc,
                    ll.technician_identity,
                    ll.extracted_findings
                FROM finance_approval_tokens fat
                JOIN financial_ledgers fl ON fl.ledger_id = fat.ledger_id
                JOIN visits v ON v.visit_id = fat.visit_id
                LEFT JOIN LATERAL (
                    SELECT technician_identity, extracted_findings
                    FROM labor_logs
                    WHERE visit_id = fat.visit_id
                    ORDER BY created_at DESC
                    LIMIT 1
                ) ll ON TRUE
                WHERE fat.approval_token = %s
                """,
                (token,),
            )
            row = cur.fetchone()
            if not row:
                return None

            if row["consumed"]:
                raise ValueError("Approval token has already been consumed.")

            if row["expires_at"] <= datetime.now(timezone.utc):
                raise ValueError("Approval token has expired.")

            if row["approval_state"] != "pending_review":
                raise ValueError(
                    f"Ledger is not pending review (state={row['approval_state']})."
                )

            if row["visit_state"] != "pending_approval":
                raise ValueError(
                    f"Visit is not awaiting approval (state={row['visit_state']})."
                )

            return FinanceApprovalBundle(
                token_id=str(row["token_id"]),
                approval_token=row["approval_token"],
                ledger_id=str(row["ledger_id"]),
                visit_id=str(row["visit_id"]),
                approval_state=row["approval_state"],
                visit_state=row["visit_state"],
                calculated_hours=float(row["calculated_hours"]),
                invoice_cents=int(row["invoice_cents"]),
                payout_cents=int(row["payout_cents"]),
                location_string=row["location_string"],
                metadata_poc=dict(row["metadata_poc"]),
                technician_identity=row["technician_identity"] or "unknown.tech@roboreliance.internal",
                extracted_findings=row["extracted_findings"] or "",
                qbo_invoice_reference=row["qbo_invoice_reference"],
            )


def commit_finance_approval_success(
    *,
    approval_token: str,
    operator_identity: str,
    qbo_invoice_reference: str,
    mcp_receipts: dict[str, Any],
) -> FinanceApprovalCommitResult:
    """Atomically finalize an approved finance workflow after MCP execution succeeds."""
    with sync_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT token_id, ledger_id, visit_id, consumed, expires_at
                FROM finance_approval_tokens
                WHERE approval_token = %s
                FOR UPDATE
                """,
                (approval_token,),
            )
            token_row = cur.fetchone()
            if not token_row:
                return FinanceApprovalCommitResult(
                    status="error",
                    visit_id="",
                    ledger_id="",
                    visit_state="",
                    approval_state="",
                    message="Unknown approval token.",
                )

            if token_row["consumed"]:
                return FinanceApprovalCommitResult(
                    status="error",
                    visit_id=str(token_row["visit_id"]),
                    ledger_id=str(token_row["ledger_id"]),
                    visit_state="",
                    approval_state="",
                    message="Approval token already consumed.",
                )

            if token_row["expires_at"] <= datetime.now(timezone.utc):
                return FinanceApprovalCommitResult(
                    status="error",
                    visit_id=str(token_row["visit_id"]),
                    ledger_id=str(token_row["ledger_id"]),
                    visit_state="",
                    approval_state="",
                    message="Approval token expired.",
                )

            cur.execute(
                """
                UPDATE financial_ledgers
                SET approval_state = 'approved',
                    qbo_invoice_reference = %s
                WHERE ledger_id = %s AND approval_state = 'pending_review'
                RETURNING ledger_id, approval_state
                """,
                (qbo_invoice_reference, str(token_row["ledger_id"])),
            )
            ledger_row = cur.fetchone()
            if not ledger_row:
                return FinanceApprovalCommitResult(
                    status="error",
                    visit_id=str(token_row["visit_id"]),
                    ledger_id=str(token_row["ledger_id"]),
                    visit_state="",
                    approval_state="",
                    message="Ledger state changed before approval could commit.",
                )

            cur.execute(
                """
                UPDATE visits
                SET current_state = 'completed'
                WHERE visit_id = %s AND current_state = 'pending_approval'
                RETURNING current_state::text AS visit_state
                """,
                (str(token_row["visit_id"]),),
            )
            visit_row = cur.fetchone()
            if not visit_row:
                raise RuntimeError("Visit state changed before approval could commit.")

            cur.execute(
                """
                UPDATE finance_approval_tokens
                SET consumed = TRUE
                WHERE approval_token = %s
                """,
                (approval_token,),
            )

            receipt = {
                "status": "approved",
                "operator_identity": operator_identity,
                "qbo_invoice_reference": qbo_invoice_reference,
                "visit_state": visit_row["visit_state"],
                "approval_state": ledger_row["approval_state"],
                "mcp_receipts": mcp_receipts,
            }
            append_audit_trail(
                conn,
                visit_id=token_row["visit_id"],
                execution_context="webhook_finance_approve",
                input_payload={
                    "approval_token": approval_token,
                    "operator_identity": operator_identity,
                },
                output_receipt=receipt,
            )

    return FinanceApprovalCommitResult(
        status="success",
        visit_id=str(token_row["visit_id"]),
        ledger_id=str(token_row["ledger_id"]),
        visit_state=visit_row["visit_state"],
        approval_state=ledger_row["approval_state"],
        qbo_invoice_reference=qbo_invoice_reference,
    )


def commit_finance_rejection(
    *,
    approval_token: str,
    operator_identity: str,
    rejection_reason: str,
) -> FinanceApprovalCommitResult:
    """Reject a pending finance review without invoking external MCP adapters."""
    with sync_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT token_id, ledger_id, visit_id, consumed, expires_at
                FROM finance_approval_tokens
                WHERE approval_token = %s
                FOR UPDATE
                """,
                (approval_token,),
            )
            token_row = cur.fetchone()
            if not token_row:
                return FinanceApprovalCommitResult(
                    status="error",
                    visit_id="",
                    ledger_id="",
                    visit_state="",
                    approval_state="",
                    message="Unknown approval token.",
                )

            if token_row["consumed"]:
                return FinanceApprovalCommitResult(
                    status="error",
                    visit_id=str(token_row["visit_id"]),
                    ledger_id=str(token_row["ledger_id"]),
                    visit_state="",
                    approval_state="",
                    message="Approval token already consumed.",
                )

            cur.execute(
                """
                UPDATE financial_ledgers
                SET approval_state = 'rejected'
                WHERE ledger_id = %s AND approval_state = 'pending_review'
                RETURNING approval_state
                """,
                (str(token_row["ledger_id"]),),
            )
            ledger_row = cur.fetchone()
            if not ledger_row:
                return FinanceApprovalCommitResult(
                    status="error",
                    visit_id=str(token_row["visit_id"]),
                    ledger_id=str(token_row["ledger_id"]),
                    visit_state="",
                    approval_state="",
                    message="Ledger state changed before rejection could commit.",
                )

            cur.execute(
                """
                UPDATE visits
                SET current_state = 'failed'
                WHERE visit_id = %s AND current_state = 'pending_approval'
                RETURNING current_state::text AS visit_state
                """,
                (str(token_row["visit_id"]),),
            )
            visit_row = cur.fetchone()

            cur.execute(
                """
                UPDATE finance_approval_tokens
                SET consumed = TRUE
                WHERE approval_token = %s
                """,
                (approval_token,),
            )

            append_audit_trail(
                conn,
                visit_id=token_row["visit_id"],
                execution_context="webhook_finance_reject",
                input_payload={
                    "approval_token": approval_token,
                    "operator_identity": operator_identity,
                    "rejection_reason": rejection_reason,
                },
                output_receipt={
                    "status": "rejected",
                    "approval_state": ledger_row["approval_state"],
                    "visit_state": visit_row["visit_state"] if visit_row else None,
                },
            )

    return FinanceApprovalCommitResult(
        status="success",
        visit_id=str(token_row["visit_id"]),
        ledger_id=str(token_row["ledger_id"]),
        visit_state=visit_row["visit_state"] if visit_row else "failed",
        approval_state=ledger_row["approval_state"],
    )


def create_visit(
    *,
    location_string: str,
    metadata_poc: dict[str, Any],
    slack_channel_id: str | None = None,
    google_space_id: str | None = None,
    source: str = "web_app",
) -> VisitRecord:
    """Deterministic visit creation — primary entry point for web app and Slack intake."""
    space_id = google_space_id or f"spaces/{uuid4()}"
    with sync_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO visits
                    (slack_channel_id, google_space_id, location_string, metadata_poc, current_state)
                VALUES (%s, %s, %s, %s::jsonb, 'initiated')
                RETURNING visit_id, slack_channel_id, google_space_id, location_string,
                          metadata_poc, current_state::text
                """,
                (
                    slack_channel_id,
                    space_id,
                    location_string,
                    _json(metadata_poc),
                ),
            )
            row = cur.fetchone()
            append_audit_trail(
                conn,
                visit_id=row["visit_id"],
                execution_context=f"visit_create_{source}",
                input_payload={
                    "slack_channel_id": slack_channel_id,
                    "location_string": location_string,
                    "metadata_poc": metadata_poc,
                    "source": source,
                },
                output_receipt={"google_space_id": space_id, "current_state": "initiated"},
            )
    return VisitRecord(
        visit_id=row["visit_id"],
        slack_channel_id=row["slack_channel_id"],
        google_space_id=row["google_space_id"],
        location_string=row["location_string"],
        metadata_poc=dict(row["metadata_poc"]),
        current_state=row["current_state"],
    )


def create_visit_from_slack(
    *,
    slack_channel_id: str,
    location_string: str,
    metadata_poc: dict[str, Any],
    google_space_id: str | None = None,
) -> VisitRecord:
    """Legacy wrapper — delegates to create_visit."""
    return create_visit(
        location_string=location_string,
        metadata_poc=metadata_poc,
        slack_channel_id=slack_channel_id,
        google_space_id=google_space_id,
        source="slack_intake",
    )


def get_visit_by_id(visit_id: str) -> dict[str, Any] | None:
    with sync_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT visit_id, slack_channel_id, google_space_id, location_string,
                       metadata_poc, current_state::text AS current_state,
                       created_at, updated_at
                FROM visits
                WHERE visit_id = %s
                """,
                (visit_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None


def _billable_hours(
    clock_in: datetime,
    clock_out: datetime,
    timesheet_metadata: dict[str, Any] | None = None,
) -> float:
    """Compute billable hours after optional break deduction."""
    metadata = timesheet_metadata or {}
    break_minutes = metadata.get("break_minutes", 0)
    try:
        break_minutes = max(0, int(break_minutes))
    except (TypeError, ValueError):
        break_minutes = 0

    duration_seconds = (clock_out - clock_in).total_seconds()
    billable_seconds = max(0.0, duration_seconds - (break_minutes * 60))
    return round(billable_seconds / 3600.0, 4)


def process_visit_signoff_transaction(
    *,
    visit_id: str,
    technician_identity: str,
    clock_in: datetime,
    clock_out: datetime,
    text_findings: str,
    timesheet_metadata: dict[str, Any] | None = None,
) -> SignoffResult:
    """
    Deterministic sign-off pipeline:
    1. Validate temporal invariants against parsed timestamps
    2. Re-read labor rows to cross-check when present
    3. Persist labor + financial ledgers inside one transaction
    4. Transition visit state to pending_approval
    """
    if clock_out <= clock_in:
        return SignoffResult(
            status="error",
            visit_id=visit_id,
            message="Validation Failed: Clock-out time cannot precede Clock-in time.",
        )

    metadata = dict(timesheet_metadata or {})
    duration_hours = _billable_hours(clock_in, clock_out, metadata)
    if duration_hours <= 0:
        return SignoffResult(
            status="error",
            visit_id=visit_id,
            message="Validation Failed: Billable hours must be greater than zero after breaks.",
        )
    invoice_cents = int(duration_hours * CLIENT_INVOICE_CENTS_PER_HOUR)
    payout_cents = int(duration_hours * CONTRACTOR_PAYOUT_CENTS_PER_HOUR)
    finance_cfg = get_platform_config("finance")
    ttl_hours = int(finance_cfg.get("approval_token_ttl_hours", 72))

    with sync_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT visit_id, current_state::text AS current_state
                FROM visits
                WHERE visit_id = %s
                FOR UPDATE
                """,
                (visit_id,),
            )
            visit = cur.fetchone()
            if not visit:
                return SignoffResult(
                    status="error",
                    visit_id=visit_id,
                    message=f"Validation Failed: Unknown visit_id {visit_id}.",
                )

            if visit["current_state"] in {"completed", "failed"}:
                return SignoffResult(
                    status="error",
                    visit_id=visit_id,
                    message=(
                        f"Validation Failed: Visit is terminal state '{visit['current_state']}'."
                    ),
                )

            cur.execute(
                """
                SELECT clock_in, clock_out
                FROM labor_logs
                WHERE visit_id = %s AND clock_in IS NOT NULL AND clock_out IS NOT NULL
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (visit_id,),
            )
            prior = cur.fetchone()
            if prior:
                stored_in = prior["clock_in"]
                stored_out = prior["clock_out"]
                if stored_in and stored_out and stored_out <= stored_in:
                    return SignoffResult(
                        status="error",
                        visit_id=visit_id,
                        message="Validation Failed: Stored labor log has invalid temporal bounds.",
                    )

            cur.execute(
                """
                INSERT INTO labor_logs
                    (visit_id, technician_identity, clock_in, clock_out,
                     extracted_findings, timesheet_metadata, is_verified)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb, TRUE)
                RETURNING log_id
                """,
                (
                    visit_id,
                    technician_identity,
                    clock_in,
                    clock_out,
                    text_findings,
                    json.dumps(metadata),
                ),
            )
            labor_log_id = cur.fetchone()["log_id"]

            cur.execute(
                """
                INSERT INTO financial_ledgers
                    (visit_id, calculated_hours, invoice_cents, payout_cents, approval_state)
                VALUES (%s, %s, %s, %s, 'pending_review')
                RETURNING ledger_id
                """,
                (visit_id, Decimal(str(round(duration_hours, 2))), invoice_cents, payout_cents),
            )
            ledger_id = cur.fetchone()["ledger_id"]

            approval_token = _issue_finance_approval_token(
                cur,
                ledger_id=ledger_id,
                visit_id=visit["visit_id"],
                ttl_hours=ttl_hours,
            )

            cur.execute(
                """
                UPDATE visits
                SET current_state = 'pending_approval'
                WHERE visit_id = %s
                """,
                (visit_id,),
            )

            receipt = {
                "status": "success",
                "calculated_hours": duration_hours,
                "invoice_cents": invoice_cents,
                "payout_cents": payout_cents,
                "labor_log_id": str(labor_log_id),
                "ledger_id": str(ledger_id),
                "approval_token": approval_token,
                "next_step": "awaiting_manager_hitl_approval",
            }
            append_audit_trail(
                conn,
                visit_id=visit_id,
                execution_context="adk_tool_process_visit_signoff",
                input_payload={
                    "visit_id": visit_id,
                    "technician_identity": technician_identity,
                    "clock_in": clock_in.isoformat(),
                    "clock_out": clock_out.isoformat(),
                    "text_findings": text_findings,
                },
                output_receipt=receipt,
            )

    return SignoffResult(
        status="success",
        visit_id=visit_id,
        calculated_hours=duration_hours,
        invoice_cents=invoice_cents,
        payout_cents=payout_cents,
        labor_log_id=str(labor_log_id),
        ledger_id=str(ledger_id),
        approval_token=approval_token,
        next_step="awaiting_manager_hitl_approval",
    )


def parse_iso8601(value: str) -> datetime:
    normalized = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def list_visits(
    *,
    state: str | None = None,
    technician: str | None = None,
    include_completed: bool = False,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []

    if state:
        clauses.append("v.current_state::text = %s")
        params.append(state)
    elif not include_completed:
        clauses.append("v.current_state::text NOT IN ('completed', 'failed')")

    if technician:
        clauses.append(
            """
            EXISTS (
                SELECT 1 FROM labor_logs ll
                WHERE ll.visit_id = v.visit_id
                  AND ll.technician_identity = %s
            )
            """
        )
        params.append(technician)

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    query = f"""
        SELECT v.visit_id, v.slack_channel_id, v.google_space_id, v.location_string,
               v.metadata_poc, v.current_state::text AS current_state,
               v.created_at, v.updated_at,
               ll.technician_identity,
               fl.approval_state AS pay_status,
               fl.payout_cents
        FROM visits v
        LEFT JOIN LATERAL (
            SELECT technician_identity FROM labor_logs
            WHERE visit_id = v.visit_id ORDER BY created_at DESC LIMIT 1
        ) ll ON TRUE
        LEFT JOIN LATERAL (
            SELECT approval_state, payout_cents FROM financial_ledgers
            WHERE visit_id = v.visit_id ORDER BY created_at DESC LIMIT 1
        ) fl ON TRUE
        {where_sql}
        ORDER BY v.created_at DESC
        LIMIT 200
    """
    with sync_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, tuple(params))
            return [dict(row) for row in cur.fetchall()]


def get_visit_detail(visit_id: str) -> dict[str, Any] | None:
    visit = get_visit_by_id(visit_id)
    if not visit:
        return None
    with sync_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT log_id, technician_identity, clock_in, clock_out,
                       extracted_findings, timesheet_metadata, is_verified, created_at
                FROM labor_logs
                WHERE visit_id = %s
                ORDER BY created_at DESC
                """,
                (visit_id,),
            )
            labor_logs = [dict(row) for row in cur.fetchall()]
            cur.execute(
                """
                SELECT ledger_id, calculated_hours, invoice_cents, payout_cents,
                       approval_state, qbo_invoice_reference, created_at, updated_at
                FROM financial_ledgers
                WHERE visit_id = %s
                ORDER BY created_at DESC
                """,
                (visit_id,),
            )
            ledgers = [dict(row) for row in cur.fetchall()]
    visit["labor_logs"] = labor_logs
    visit["financial_ledgers"] = ledgers
    return visit


def clock_in_transaction(
    *,
    visit_id: str,
    technician_identity: str,
) -> dict[str, Any]:
    with sync_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT visit_id, current_state::text AS current_state
                FROM visits WHERE visit_id = %s FOR UPDATE
                """,
                (visit_id,),
            )
            visit = cur.fetchone()
            if not visit:
                return {"status": "error", "message": f"Unknown visit_id {visit_id}."}
            if visit["current_state"] not in {"initiated", "active"}:
                return {
                    "status": "error",
                    "message": f"Visit state '{visit['current_state']}' does not allow clock-in.",
                }
            cur.execute(
                """
                SELECT log_id FROM labor_logs
                WHERE visit_id = %s AND clock_in IS NOT NULL AND clock_out IS NULL
                ORDER BY created_at DESC LIMIT 1
                """,
                (visit_id,),
            )
            if cur.fetchone():
                return {"status": "error", "message": "Technician already clocked in for this visit."}

            now = datetime.now(timezone.utc)
            cur.execute(
                """
                INSERT INTO labor_logs (visit_id, technician_identity, clock_in, is_verified)
                VALUES (%s, %s, %s, FALSE)
                RETURNING log_id
                """,
                (visit_id, technician_identity, now),
            )
            log_id = cur.fetchone()["log_id"]
            cur.execute(
                """
                UPDATE visits SET current_state = 'active' WHERE visit_id = %s
                """,
                (visit_id,),
            )
            receipt = {
                "status": "success",
                "visit_id": visit_id,
                "labor_log_id": str(log_id),
                "clock_in": now.isoformat(),
                "visit_state": "active",
            }
            append_audit_trail(
                conn,
                visit_id=visit_id,
                execution_context="api_clock_in",
                input_payload={
                    "visit_id": visit_id,
                    "technician_identity": technician_identity,
                },
                output_receipt=receipt,
            )
    return receipt


def list_pending_finance() -> list[dict[str, Any]]:
    with sync_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT fl.ledger_id, fl.visit_id, fl.calculated_hours,
                       fl.invoice_cents, fl.payout_cents, fl.approval_state,
                       fl.created_at, v.location_string, v.metadata_poc,
                       ll.technician_identity, ll.extracted_findings
                FROM financial_ledgers fl
                JOIN visits v ON v.visit_id = fl.visit_id
                LEFT JOIN LATERAL (
                    SELECT technician_identity, extracted_findings
                    FROM labor_logs
                    WHERE visit_id = fl.visit_id
                    ORDER BY created_at DESC LIMIT 1
                ) ll ON TRUE
                WHERE fl.approval_state = 'pending_review'
                ORDER BY fl.created_at ASC
                """
            )
            return [dict(row) for row in cur.fetchall()]


def get_finance_ledger_detail(ledger_id: str) -> dict[str, Any] | None:
    with sync_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT fl.ledger_id, fl.visit_id, fl.calculated_hours,
                       fl.invoice_cents, fl.payout_cents, fl.approval_state,
                       fl.qbo_invoice_reference, fl.created_at, fl.updated_at,
                       v.location_string, v.metadata_poc, v.current_state::text AS visit_state,
                       v.slack_channel_id, v.google_space_id,
                       ll.technician_identity, ll.clock_in, ll.clock_out,
                       ll.extracted_findings, ll.timesheet_metadata
                FROM financial_ledgers fl
                JOIN visits v ON v.visit_id = fl.visit_id
                LEFT JOIN LATERAL (
                    SELECT technician_identity, clock_in, clock_out,
                           extracted_findings, timesheet_metadata
                    FROM labor_logs WHERE visit_id = fl.visit_id
                    ORDER BY created_at DESC LIMIT 1
                ) ll ON TRUE
                WHERE fl.ledger_id = %s
                """,
                (ledger_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            detail = dict(row)
            cur.execute(
                """
                SELECT audit_id, execution_context, input_payload, output_receipt, timestamp
                FROM immutable_audit_trail
                WHERE visit_id = %s
                ORDER BY timestamp DESC LIMIT 10
                """,
                (str(detail["visit_id"]),),
            )
            detail["audit_trail"] = [dict(r) for r in cur.fetchall()]
            cur.execute(
                """
                SELECT approval_token, consumed, expires_at
                FROM finance_approval_tokens
                WHERE ledger_id = %s AND consumed = FALSE
                ORDER BY created_at DESC LIMIT 1
                """,
                (ledger_id,),
            )
            token_row = cur.fetchone()
            if token_row:
                detail["approval_token"] = token_row["approval_token"]
            return detail


def list_finance_ledgers(
    *,
    approval_state: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []

    if approval_state:
        clauses.append("fl.approval_state = %s")
        params.append(approval_state)

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)

    with sync_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT fl.ledger_id, fl.visit_id, fl.calculated_hours,
                       fl.invoice_cents, fl.payout_cents, fl.approval_state,
                       fl.qbo_invoice_reference, fl.created_at, fl.updated_at,
                       v.location_string, v.metadata_poc,
                       ll.technician_identity, ll.extracted_findings
                FROM financial_ledgers fl
                JOIN visits v ON v.visit_id = fl.visit_id
                LEFT JOIN LATERAL (
                    SELECT technician_identity, extracted_findings FROM labor_logs
                    WHERE visit_id = fl.visit_id ORDER BY created_at DESC LIMIT 1
                ) ll ON TRUE
                {where_sql}
                ORDER BY
                    CASE fl.approval_state WHEN 'pending_review' THEN 0 ELSE 1 END,
                    fl.created_at DESC
                LIMIT %s
                """,
                tuple(params),
            )
            return [dict(row) for row in cur.fetchall()]


def list_finance_history(limit: int = 100) -> list[dict[str, Any]]:
    """Legacy wrapper — returns only approved/rejected ledgers."""
    return list_finance_ledgers(limit=limit)


def get_visit_by_google_space_id(google_space_id: str) -> dict[str, Any] | None:
    with sync_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT visit_id, slack_channel_id, google_space_id, location_string,
                       metadata_poc, current_state::text AS current_state
                FROM visits WHERE google_space_id = %s
                """,
                (google_space_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None


def get_visit_by_slack_channel_id(slack_channel_id: str) -> dict[str, Any] | None:
    with sync_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT v.visit_id, v.slack_channel_id, v.google_space_id, v.location_string,
                       v.metadata_poc, v.current_state::text AS current_state
                FROM visits v
                WHERE v.slack_channel_id = %s
                UNION
                SELECT v.visit_id, v.slack_channel_id, v.google_space_id, v.location_string,
                       v.metadata_poc, v.current_state::text AS current_state
                FROM slack_channel_visit_bindings b
                JOIN visits v ON v.visit_id = b.visit_id
                WHERE b.slack_channel_id = %s
                LIMIT 1
                """,
                (slack_channel_id, slack_channel_id),
            )
            row = cur.fetchone()
            return dict(row) if row else None


def get_visit_context_payload(visit_id: str) -> dict[str, Any]:
    detail = get_visit_detail(visit_id)
    if not detail:
        return {"status": "error", "message": f"visit_id {visit_id} not found."}
    active_log = next(
        (log for log in detail.get("labor_logs", []) if log.get("clock_in") and not log.get("clock_out")),
        None,
    )
    return {
        "status": "success",
        "visit_id": str(detail["visit_id"]),
        "location_string": detail["location_string"],
        "current_state": detail["current_state"],
        "slack_channel_id": detail.get("slack_channel_id"),
        "google_space_id": detail.get("google_space_id"),
        "metadata_poc": detail.get("metadata_poc"),
        "active_clock_in": active_log["clock_in"].isoformat() if active_log else None,
        "labor_log_count": len(detail.get("labor_logs", [])),
    }


def upsert_channel_ingestion_cursor(
    *,
    channel_type: str,
    channel_id: str,
    visit_id: str | None,
    last_message_time: datetime | None,
    last_message_name: str | None,
) -> None:
    with sync_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO channel_ingestion_cursors
                    (channel_type, channel_id, visit_id, last_message_time, last_message_name)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (channel_type, channel_id) DO UPDATE SET
                    visit_id = COALESCE(EXCLUDED.visit_id, channel_ingestion_cursors.visit_id),
                    last_message_time = COALESCE(EXCLUDED.last_message_time, channel_ingestion_cursors.last_message_time),
                    last_message_name = COALESCE(EXCLUDED.last_message_name, channel_ingestion_cursors.last_message_name),
                    updated_at = CURRENT_TIMESTAMP
                """,
                (channel_type, channel_id, visit_id, last_message_time, last_message_name),
            )


def touch_web_chat_session(
    *,
    session_id: str,
    user_identity: str,
    visit_id: str | None,
) -> None:
    with sync_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO web_chat_sessions (session_id, user_identity, visit_id)
                VALUES (%s, %s, %s)
                ON CONFLICT (session_id) DO UPDATE SET
                    visit_id = COALESCE(EXCLUDED.visit_id, web_chat_sessions.visit_id),
                    updated_at = CURRENT_TIMESTAMP
                """,
                (session_id, user_identity, visit_id),
            )

