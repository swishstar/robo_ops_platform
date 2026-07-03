"""
Shared ADK agent turn handler for Web Chat, Google Chat, and Slack.

AI interprets; tools validate and execute. Channel context is passed in
deterministically — never inferred solely by the model.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from agent_def import (
    get_visit_context,
    lookup_field_learnings,
    lookup_technical_sop,
    process_visit_signoff,
)

logger = logging.getLogger(__name__)


@dataclass
class ChannelContext:
    surface: str  # web_chat | google_chat | slack
    channel_id: str | None = None
    thread_id: str | None = None
    visit_id: str | None = None
    user_identity: str = "unknown@roboreliance.internal"


@dataclass
class AgentTurnResult:
    reply_text: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)


def _extract_iso_times(text: str) -> tuple[str | None, str | None]:
    """Best-effort ISO-8601 extraction from natural language payloads."""
    patterns = [
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?",
        r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}(?::\d{2})?",
    ]
    found: list[str] = []
    for pattern in patterns:
        found.extend(re.findall(pattern, text))
    if len(found) >= 2:
        return found[0], found[1]
    return None, None


def _looks_like_sop_query(text: str) -> bool:
    lowered = text.lower()
    keywords = ("sop", "manual", "error code", "how do", "procedure", "maintenance", "troubleshoot")
    return any(k in lowered for k in keywords) or text.strip().endswith("?")


def _looks_like_field_query(text: str) -> bool:
    lowered = text.lower()
    keywords = ("field note", "last visit", "learned", "on site", "remember", "previous repair")
    return any(k in lowered for k in keywords)


def _looks_like_clock_in(text: str) -> bool:
    lowered = text.lower()
    return any(p in lowered for p in ("clock in", "clock-in", "clocking in", "start shift", "on site now"))


def _looks_like_clock_out(text: str) -> bool:
    lowered = text.lower()
    return any(
        p in lowered
        for p in ("clock out", "clock-out", "sign off", "sign-off", "done for the day", "finished visit")
    )


def _run_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    dispatch: dict[str, Callable[..., Any]] = {
        "lookup_technical_sop": lambda: lookup_technical_sop(args.get("query", "")),
        "lookup_field_learnings": lambda: lookup_field_learnings(args.get("query", "")),
        "get_visit_context": lambda: get_visit_context(args.get("visit_id", "")),
        "process_visit_signoff": lambda: process_visit_signoff(
            visit_id=args.get("visit_id", ""),
            clock_in_str=args.get("clock_in_str", ""),
            clock_out_str=args.get("clock_out_str", ""),
            text_findings=args.get("text_findings", ""),
            technician_identity=args.get("technician_identity", "field.tech@roboreliance.internal"),
        ),
    }
    if name not in dispatch:
        return {"status": "error", "message": f"Unknown tool {name}"}
    result = dispatch[name]()
    if isinstance(result, str):
        return {"status": "success", "content": result}
    return result


def _gemini_turn(message: str, context: ChannelContext, visit_hint: dict[str, Any] | None) -> AgentTurnResult | None:
    api_key = os.getenv("GOOGLE_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        import google.generativeai as genai

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.0-flash")
        system = (
            "You are Robo Reliance field ops assistant. "
            "Use tools for SOP lookup, field learnings, visit context, and sign-off. "
            "Never invent billing numbers. Cite sources."
        )
        prompt = json.dumps(
            {
                "message": message,
                "surface": context.surface,
                "visit": visit_hint,
                "user": context.user_identity,
            },
            default=str,
        )
        response = model.generate_content([system, prompt])
        text = response.text if response.text else ""
        return AgentTurnResult(reply_text=text)
    except Exception as exc:
        logger.warning("Gemini turn failed, falling back to rules: %s", exc)
        return None


def handle_agent_turn(message: str, context: ChannelContext) -> AgentTurnResult:
    """
    Process one user message across any chat surface.
    Rule-based routing with optional Gemini enhancement.
    """
    text = message.strip()
    if not text:
        return AgentTurnResult(reply_text="Please send a message or question.")

    visit_hint: dict[str, Any] | None = None
    if context.visit_id:
        visit_hint = get_visit_context(context.visit_id)
        if isinstance(visit_hint, dict) and visit_hint.get("status") == "success":
            pass
        else:
            visit_hint = None

    gemini_result = _gemini_turn(text, context, visit_hint)
    if gemini_result and not _looks_like_clock_out(text) and not _looks_like_clock_in(text):
        return gemini_result

    tool_calls: list[dict[str, Any]] = []
    citations: list[str] = []

    if _looks_like_clock_in(text):
        if not context.visit_id:
            return AgentTurnResult(
                reply_text="I need a visit context to clock in. Open a visit in the web app or use a bound channel."
            )
        from database import clock_in_transaction

        result = clock_in_transaction(
            visit_id=context.visit_id,
            technician_identity=context.user_identity,
        )
        tool_calls.append({"tool": "clock_in", "result": result})
        if result.get("status") == "success":
            return AgentTurnResult(
                reply_text=f"Clocked in at {result['clock_in']} for visit {context.visit_id}.",
                tool_calls=tool_calls,
            )
        return AgentTurnResult(reply_text=result.get("message", "Clock-in failed."), tool_calls=tool_calls)

    if _looks_like_clock_out(text):
        if not context.visit_id:
            return AgentTurnResult(
                reply_text="I need a visit context to sign off. Provide visit_id or use a bound channel."
            )
        clock_in_str, clock_out_str = _extract_iso_times(text)
        if not clock_out_str:
            clock_out_str = datetime.now(timezone.utc).isoformat()
        if not clock_in_str and visit_hint:
            clock_in_str = visit_hint.get("active_clock_in")
        if not clock_in_str:
            return AgentTurnResult(
                reply_text="Please include clock-in and clock-out times (ISO-8601), or clock in first."
            )
        findings = text
        for ts in (clock_in_str, clock_out_str):
            if ts:
                findings = findings.replace(ts, "")
        findings = findings.strip() or "Visit completed — findings captured from chat."
        args = {
            "visit_id": context.visit_id,
            "clock_in_str": clock_in_str,
            "clock_out_str": clock_out_str,
            "text_findings": findings,
            "technician_identity": context.user_identity,
        }
        result = _run_tool("process_visit_signoff", args)
        tool_calls.append({"tool": "process_visit_signoff", "args": args, "result": result})
        if result.get("status") == "success":
            return AgentTurnResult(
                reply_text=(
                    f"Sign-off recorded: {result.get('calculated_hours')} hours. "
                    f"Status: pending manager approval in the Ops web app."
                ),
                tool_calls=tool_calls,
            )
        return AgentTurnResult(
            reply_text=result.get("message", "Sign-off failed."),
            tool_calls=tool_calls,
        )

    if text.lower().startswith("@agent remember:") or text.lower().startswith("remember:"):
        note = re.sub(r"^@?agent\s+remember:\s*", "", text, flags=re.I)
        from field_learnings_ingest import ingest_text_learning

        doc_id = ingest_text_learning(
            text=note,
            visit_id=context.visit_id,
            channel_type=context.surface,
            channel_id=context.channel_id,
            author=context.user_identity,
        )
        return AgentTurnResult(
            reply_text=f"Captured to field learnings (doc: {doc_id}).",
            citations=[doc_id],
        )

    if _looks_like_field_query(text) or "field" in text.lower():
        result = _run_tool("lookup_field_learnings", {"query": text})
        content = result.get("content", str(result))
        tool_calls.append({"tool": "lookup_field_learnings", "result": result})
        citations.append("field_learnings")
        return AgentTurnResult(reply_text=content, tool_calls=tool_calls, citations=citations)

    if _looks_like_sop_query(text):
        result = _run_tool("lookup_technical_sop", {"query": text})
        content = result.get("content", str(result))
        tool_calls.append({"tool": "lookup_technical_sop", "result": result})
        citations.append("sop_library")
        return AgentTurnResult(reply_text=content, tool_calls=tool_calls, citations=citations)

    if context.visit_id:
        ctx = _run_tool("get_visit_context", {"visit_id": context.visit_id})
        tool_calls.append({"tool": "get_visit_context", "result": ctx})
        return AgentTurnResult(
            reply_text=(
                f"Visit {context.visit_id} at {ctx.get('location_string')} "
                f"is {ctx.get('current_state')}. Ask me about SOPs, field learnings, "
                "or say 'clock in' / 'clock out' with times and findings."
            ),
            tool_calls=tool_calls,
        )

    return AgentTurnResult(
        reply_text=(
            "I can help with SOP lookups, field learnings, visit context, and timekeeping. "
            "Try: 'What is error code A-17?' or 'clock out' with ISO times and findings."
        )
    )
