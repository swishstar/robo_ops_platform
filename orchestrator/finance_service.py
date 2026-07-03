"""
Finance approval execution — shared by webhook and /api/v1/finance/approve.
"""

from __future__ import annotations

import logging
from typing import Any, Literal, Optional

from fastapi import HTTPException, status

from database import (
    commit_finance_approval_success,
    commit_finance_rejection,
    get_platform_configs,
    load_finance_approval_bundle,
)
from mcp_client import MCPClientError, linkedin_client, quickbooks_client

logger = logging.getLogger(__name__)


async def execute_finance_approval(
    *,
    approval_token: str,
    operator_identity: str,
    action: Literal["approve", "reject"] = "approve",
    rejection_reason: Optional[str] = None,
) -> dict[str, Any]:
    configs = get_platform_configs(["finance", "quickbooks", "linkedin"])
    finance_cfg = configs.get("finance", {})
    if finance_cfg.get("require_operator_identity") and not operator_identity.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="operator_identity is required by platform finance policy.",
        )

    try:
        bundle = load_finance_approval_bundle(approval_token)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    if bundle is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Approval token not found.",
        )

    if action == "reject":
        if not rejection_reason or len(rejection_reason.strip()) < 5:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="rejection_reason is required when action is reject.",
            )
        result = commit_finance_rejection(
            approval_token=approval_token,
            operator_identity=operator_identity.strip(),
            rejection_reason=rejection_reason.strip(),
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

    invoice_receipt = mcp_receipts.get("quickbooks_invoice", {})
    qbo_invoice_reference = (
        invoice_receipt.get("invoice_reference")
        or invoice_receipt.get("qbo_invoice_id")
        or invoice_receipt.get("receipt_id")
        or f"QBO-SIM-{bundle.ledger_id[:8]}"
    )

    commit_result = commit_finance_approval_success(
        approval_token=approval_token,
        operator_identity=operator_identity.strip(),
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
        "operator_identity": operator_identity.strip(),
    }
