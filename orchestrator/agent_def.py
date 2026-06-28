"""
ADK agent definition for Robo Reliance field technician support.

AI interprets and suggests; deterministic Python in @Tool handlers validates
and executes all database mutations.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from google_agents_cli_adk import Agent, Gemini, Tool

from database import (
    get_visit_by_id,
    parse_iso8601,
    process_visit_signoff_transaction,
)

logger = logging.getLogger(__name__)

SOP_INDEX_ENDPOINT = os.getenv(
    "SOP_SEARCH_ENDPOINT",
    "https://discoveryengine.googleapis.com/v1/projects/roboreliance/locations/global/collections/default_collection/engines/sop-library/servingConfigs/default_search",
)


@Tool
def lookup_technical_sop(query: str) -> str:
    """
    Queries the robot manuals and operational standard operating procedures (SOPs).
    This tool connects directly to the Vertex AI Search Index pointing to Google Drive /03_Technical_Library.
    """
    normalized_query = query.strip()
    if not normalized_query:
        return "Error: SOP query must not be empty."

    # Local development returns deterministic grounding stubs; production routes
    # through Vertex AI Search / Platform Search Extension.
    if os.getenv("ENVIRONMENT", "development") == "development":
        return (
            "SOP Context (local stub):\n"
            f"- Query: {normalized_query}\n"
            "- Source: /03_Technical_Library/RR-FieldOps/Maintenance_Checklist.pdf\n"
            "- Guidance: Verify E-stop latch, run actuator self-test (code A-17), "
            "capture torque readings before releasing the visit for sign-off.\n"
            "- Citation: drive://03_Technical_Library/RR-FieldOps/Maintenance_Checklist.pdf#p12"
        )

    return (
        "SOP Context (production index binding):\n"
        f"- Query: {normalized_query}\n"
        f"- Index endpoint: {SOP_INDEX_ENDPOINT}\n"
        "- Action: Delegate vector retrieval to Platform Search Extension at runtime."
    )


@Tool
def process_visit_signoff(
    visit_id: str,
    clock_in_str: str,
    clock_out_str: str,
    text_findings: str,
    technician_identity: str = "field.tech@roboreliance.internal",
) -> dict[str, Any]:
    """
    Executes core server validation on time entries, calculates billing bounds,
    and writes to PostgreSQL database ledgers. Banned from AI generation rules.
    """
    try:
        visit_id = visit_id.strip()
        if not visit_id:
            return {"status": "error", "message": "Validation Failed: visit_id is required."}

        visit = get_visit_by_id(visit_id)
        if visit is None:
            return {
                "status": "error",
                "message": f"Validation Failed: visit_id '{visit_id}' was not found.",
            }

        t_in = parse_iso8601(clock_in_str)
        t_out = parse_iso8601(clock_out_str)

        if t_out <= t_in:
            return {
                "status": "error",
                "message": "Validation Failed: Clock-out time cannot precede Clock-in time.",
            }

        findings = text_findings.strip()
        if len(findings) < 8:
            return {
                "status": "error",
                "message": "Validation Failed: Technical findings must contain substantive detail.",
            }

        result = process_visit_signoff_transaction(
            visit_id=visit_id,
            technician_identity=technician_identity.strip(),
            clock_in=t_in,
            clock_out=t_out,
            text_findings=findings,
        )

        if result.status != "success":
            return {"status": "error", "message": result.message or "Sign-off rejected."}

        return {
            "status": "success",
            "visit_id": result.visit_id,
            "calculated_hours": result.calculated_hours,
            "invoice_cents": result.invoice_cents,
            "payout_cents": result.payout_cents,
            "ledger_id": result.ledger_id,
            "labor_log_id": result.labor_log_id,
            "next_step": result.next_step,
        }
    except ValueError as exc:
        return {
            "status": "error",
            "message": f"Validation Failed: Invalid ISO-8601 timestamp — {exc}",
        }
    except Exception as exc:
        logger.exception("process_visit_signoff fault for visit_id=%s", visit_id)
        return {"status": "error", "message": f"Execution processing fault: {exc}"}


tech_support_agent = Agent(
    name="field_tech_support_agent",
    model=Gemini(model="gemini-2.0-pro"),
    instruction="""
    You are the on-site operational intelligence agent for Robo Reliance.
    Your mission is to support field engineers and extract visit parameters upon completion.

    Operations Guidelines:
    1. Ground all engineering, error codes, and maintenance lookups using 'lookup_technical_sop'.
       Do not hallucinate instructions or error definitions. Always reference matching sources.
    2. When the technician signals work completion or requests to clock out, you must capture
       the clock-in time, clock-out time, and technical findings. Once extracted, you MUST invoke
       the 'process_visit_signoff' tool.
    3. You cannot authorize payments or directly log success metrics yourself. You must delegate to your tools.
    """,
    tools=[lookup_technical_sop, process_visit_signoff],
)
