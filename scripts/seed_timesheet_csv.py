#!/usr/bin/env python3
"""Seed local Postgres from the Technician Site Visit Timesheet CSV.

Usage (local Docker):
  docker compose up -d postgres
  python3 scripts/seed_timesheet_csv.py

Idempotent: rows keyed by google_space_id = spaces/seed-<hash>.
Re-runs refresh that labor row's hours, sheet amount, and payment flags
without touching any other technician later added to the same visit.

Payout amounts on imported rows come from the CSV Amount column (explicit).
technician_rates.payout_cents_per_hour is the median implied hourly from those
amounts so new timesheet rows use a real per-technician rate.
Client invoice rate is stored on the rate row (default $150/hr) until edited.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    print("psycopg2 required. Run inside the orchestrator container or: pip install psycopg2-binary", file=sys.stderr)
    sys.exit(1)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CSV = (
    REPO_ROOT
    / "deployment"
    / "fixtures"
    / "timesheets"
    / "technician_site_visit_invoices.csv"
)
DEFAULT_DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://engine_admin:development_vault_password@localhost:5432/roboreliance_local",
)

# Stored on technician_rates.invoice_cents_per_hour until finance sets a client rate.
# CSV Amount is contractor pay, not this figure. Not used as the sheet Amount.
ESTIMATE_CLIENT_INVOICE_CENTS_PER_HOUR = 15000
SCHEMA_FILES = (
    REPO_ROOT / "init-scripts" / "06_visit_work_order.sql",
    REPO_ROOT / "init-scripts" / "07_labor_payment_flags_and_rates.sql",
)

PLACEHOLDER_POC = {
    "name": "CSV Seed Import",
    "phone": "+10000000000",
    "email": "seed@roboreliance.internal",
}

SITE_CLIENT_MAP = {
    "bonduelle": "chef",
    "cookunity": "chef",
    "amy's kitchen": "chef",
    "amys kitchen": "chef",
    "robo reliance": "roboreliance",
}


def _truthy(value: str) -> Optional[bool]:
    v = (value or "").strip().upper()
    if v in {"TRUE", "YES", "Y", "1"}:
        return True
    if v in {"FALSE", "NO", "N", "0"}:
        return False
    if v in {"", "NA", "N/A"}:
        return None
    return None


def _parse_amount_cents(raw: str) -> Optional[int]:
    s = (raw or "").strip().replace("$", "").replace(",", "")
    if not s:
        return None
    try:
        return int(round(float(s) * 100))
    except ValueError:
        return None


def _parse_duration_hours(raw: str) -> Optional[float]:
    s = (raw or "").strip()
    if not s:
        return None
    parts = s.split(":")
    try:
        if len(parts) == 3:
            h, m, sec = (int(parts[0]), int(parts[1]), int(parts[2]))
            return h + m / 60.0 + sec / 3600.0
        if len(parts) == 2:
            h, m = (int(parts[0]), int(parts[1]))
            return h + m / 60.0
    except ValueError:
        return None
    return None


def _parse_visit_date(raw: str) -> Optional[datetime]:
    s = (raw or "").strip()
    if not s:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _parse_clock(day: datetime, time_raw: str) -> Optional[datetime]:
    s = (time_raw or "").strip()
    if not s or day is None:
        return None
    for fmt in ("%H:%M", "%H:%M:%S", "%I:%M %p", "%I:%M:%S %p"):
        try:
            t = datetime.strptime(s, fmt)
            return day.replace(hour=t.hour, minute=t.minute, second=t.second)
        except ValueError:
            continue
    # Forms sometimes emit "9:30" without zero-padding hour in 24h — already covered.
    return None


def _normalize_email(email: str) -> str:
    e = (email or "").strip().lower()
    e = re.sub(r"-old\d*$", "", e)
    return e


def _technician_identity(row: Dict[str, str]) -> str:
    name = (row.get("Name") or "").strip()
    email = _normalize_email(row.get("Email Address") or "")
    if name and email:
        return f"{name} <{email}>"
    return name or email or "unknown@roboreliance.internal"


def _client_id_for_site(site: str) -> str:
    return SITE_CLIENT_MAP.get(site.strip().lower(), "chef")


def _seed_space_id(row: Dict[str, str]) -> str:
    key = "|".join(
        [
            (row.get("Email Address") or "").strip().lower(),
            (row.get("Customer/Site Name") or "").strip().lower(),
            (row.get("Date of Site Visit") or "").strip(),
            (row.get("Time of Arrival (on site)") or "").strip(),
            (row.get("Time of Departure (from site)") or "").strip(),
            (row.get("Amount") or "").strip(),
            (row.get("Client Work Order or Job Number (if applicable)") or "").strip(),
        ]
    )
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
    return f"spaces/seed-{digest}"


def _location_string(row: Dict[str, str]) -> str:
    site = (row.get("Customer/Site Name") or "").strip()
    wo = (row.get("Client Work Order or Job Number (if applicable)") or "").strip()
    if wo:
        return f"{site} — {wo}"
    return site


def _approval_and_state(row: Dict[str, str]) -> Tuple[str, str]:
    paid_contractor = _truthy(row.get("Paid to Contractor") or "")
    if paid_contractor is True:
        return "approved", "completed"
    if paid_contractor is False:
        return "pending_review", "pending_approval"
    return "pending_review", "pending_approval"


def _execute_sql_file(cur: Any, path: Path) -> None:
    lines: List[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("--"):
            continue
        lines.append(line)
    for statement in "\n".join(lines).split(";"):
        sql = statement.strip()
        if sql:
            cur.execute(sql)


def _median(values: List[int]) -> int:
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return int(round((ordered[mid - 1] + ordered[mid]) / 2.0))


def _upsert_technician_rates(cur: Any, samples: Dict[str, Dict[str, Any]]) -> int:
    written = 0
    for email, bucket in sorted(samples.items()):
        hourly: List[int] = bucket["hourly"]
        if not hourly:
            continue
        cur.execute(
            """
            INSERT INTO technician_rates
                (technician_email, technician_name, payout_cents_per_hour, invoice_cents_per_hour)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (technician_email) DO UPDATE
            SET technician_name = COALESCE(EXCLUDED.technician_name, technician_rates.technician_name),
                payout_cents_per_hour = EXCLUDED.payout_cents_per_hour,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                email,
                bucket.get("name") or None,
                _median(hourly),
                ESTIMATE_CLIENT_INVOICE_CENTS_PER_HOUR,
            ),
        )
        written += 1
    return written


def _note_rate(
    samples: Dict[str, Dict[str, Any]],
    row: Dict[str, str],
    duration_hours: float,
    payout_cents: int,
) -> None:
    email = _normalize_email(row.get("Email Address") or "")
    if not email or "@" not in email or duration_hours <= 0 or payout_cents <= 0:
        return
    bucket = samples.setdefault(email, {"hourly": [], "name": ""})
    bucket["hourly"].append(int(round(payout_cents / duration_hours)))
    name = (row.get("Name") or "").strip()
    if name:
        bucket["name"] = name


def _refresh_seed_row(
    cur: Any,
    visit_id: Any,
    tech: str,
    clock_in: datetime,
    clock_out: datetime,
    notes: str,
    timesheet_metadata: Dict[str, Any],
    duration_hours: float,
    payout_cents: int,
    invoice_cents: int,
    paid_contractor: Optional[bool],
    billed: Optional[bool],
    paid_client: Optional[bool],
) -> None:
    """Update the original CSV labor row only, leaving any later technician rows alone."""
    cur.execute(
        """
        SELECT log_id FROM labor_logs
        WHERE visit_id = %s AND technician_identity = %s
        ORDER BY created_at ASC
        LIMIT 1
        """,
        (visit_id, tech),
    )
    labor = cur.fetchone()
    if not labor:
        cur.execute(
            """
            SELECT log_id FROM labor_logs
            WHERE visit_id = %s
            ORDER BY created_at ASC
            LIMIT 1
            """,
            (visit_id,),
        )
        labor = cur.fetchone()
    hours = Decimal(str(round(duration_hours, 2)))
    if labor:
        cur.execute(
            """
            UPDATE labor_logs
            SET clock_in = %s,
                clock_out = %s,
                extracted_findings = %s,
                timesheet_metadata = %s::jsonb,
                is_verified = TRUE,
                paid_to_contractor = %s,
                billed_to_client = %s,
                paid_by_client = %s,
                billable_hours = %s,
                amount_cents = %s,
                payout_cents = %s,
                invoice_cents = %s,
                amount_source = 'explicit'
            WHERE log_id = %s
            """,
            (
                clock_in,
                clock_out,
                notes,
                json.dumps(timesheet_metadata),
                paid_contractor,
                billed,
                paid_client,
                hours,
                payout_cents,
                payout_cents,
                invoice_cents,
                labor["log_id"],
            ),
        )
    cur.execute(
        """
        UPDATE financial_ledgers
        SET calculated_hours = %s,
            invoice_cents = %s,
            payout_cents = %s
        WHERE ledger_id = (
            SELECT ledger_id FROM financial_ledgers
            WHERE visit_id = %s
            ORDER BY created_at ASC
            LIMIT 1
        )
        """,
        (hours, invoice_cents, payout_cents, visit_id),
    )


def load_rows(csv_path: Path) -> List[Dict[str, str]]:
    with csv_path.open(newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    out: List[Dict[str, str]] = []
    for row in rows:
        site = (row.get("Customer/Site Name") or "").strip()
        if not site:
            continue
        if site.lower() == "test1":
            continue
        out.append(row)
    return out


def seed(database_url: str, csv_path: Path, dry_run: bool = False) -> int:
    rows = load_rows(csv_path)
    print(f"Loaded {len(rows)} seedable rows from {csv_path}")

    if dry_run:
        for row in rows[:5]:
            print(" sample:", _location_string(row), _technician_identity(row), row.get("Amount"))
        print("dry-run: no DB writes")
        return 0

    conn = psycopg2.connect(database_url)
    inserted = 0
    updated = 0
    skipped = 0
    try:
        with conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                for schema_path in SCHEMA_FILES:
                    _execute_sql_file(cur, schema_path)
                rate_samples: Dict[str, Dict[str, Any]] = {}
                for row in rows:
                    space_id = _seed_space_id(row)
                    day = _parse_visit_date(row.get("Date of Site Visit") or "")
                    if day is None:
                        print(f" skip (bad date): {row.get('Customer/Site Name')!r}")
                        skipped += 1
                        continue

                    clock_in = _parse_clock(day, row.get("Time of Arrival (on site)") or "")
                    clock_out = _parse_clock(day, row.get("Time of Departure (from site)") or "")
                    duration_hours = _parse_duration_hours(row.get("Duration") or "")
                    if duration_hours is None and clock_in and clock_out and clock_out > clock_in:
                        duration_hours = (clock_out - clock_in).total_seconds() / 3600.0
                    if clock_in is None and duration_hours is not None:
                        clock_in = day.replace(hour=9, minute=0, second=0)
                    if clock_out is None and clock_in is not None and duration_hours is not None:
                        clock_out = clock_in + timedelta(hours=duration_hours)
                    if clock_in is None or clock_out is None:
                        clock_in = day.replace(hour=9, minute=0, second=0)
                        clock_out = day.replace(hour=10, minute=0, second=0)
                        duration_hours = duration_hours or 1.0
                    if duration_hours is None or duration_hours <= 0:
                        duration_hours = max(
                            (clock_out - clock_in).total_seconds() / 3600.0,
                            0.25,
                        )

                    payout_cents = _parse_amount_cents(row.get("Amount") or "")
                    if payout_cents is None:
                        payout_cents = 0

                    billed = _truthy(row.get("Billed to Client") or "")
                    paid_contractor = _truthy(row.get("Paid to Contractor") or "")
                    paid_client = _truthy(row.get("Paid by Client") or "")
                    if billed is True:
                        invoice_cents = int(
                            round(duration_hours * ESTIMATE_CLIENT_INVOICE_CENTS_PER_HOUR)
                        )
                    else:
                        invoice_cents = 0

                    implied_hourly = (
                        int(round(payout_cents / duration_hours))
                        if duration_hours > 0 and payout_cents > 0
                        else None
                    )

                    approval_state, visit_state = _approval_and_state(row)
                    tech = _technician_identity(row)
                    site = (row.get("Customer/Site Name") or "").strip()
                    notes = (row.get("Notes") or "").strip() or "Imported from timesheet CSV."
                    timesheet_metadata: Dict[str, Any] = {
                        "service_date": day.date().isoformat(),
                        "customer_site_name": site,
                        "work_order_number": (
                            row.get("Client Work Order or Job Number (if applicable)") or ""
                        ).strip()
                        or None,
                        "invoice_number": (
                            row.get("Your Invoice Number (if applicable)") or ""
                        ).strip()
                        or None,
                        "source": "timesheet_csv_seed",
                        "csv_email": (row.get("Email Address") or "").strip(),
                        "paid_to_contractor": _truthy(row.get("Paid to Contractor") or ""),
                        "billed_to_client": billed,
                        "paid_by_client": _truthy(row.get("Paid by Client") or ""),
                        "payout_amount_cents": payout_cents,
                        "implied_hourly_cents": implied_hourly,
                        "attestation": True,
                    }
                    # Drop nulls for cleaner JSON
                    timesheet_metadata = {
                        k: v for k, v in timesheet_metadata.items() if v is not None
                    }

                    _note_rate(rate_samples, row, duration_hours, payout_cents)
                    hours = Decimal(str(round(duration_hours, 2)))

                    cur.execute(
                        "SELECT visit_id FROM visits WHERE google_space_id = %s",
                        (space_id,),
                    )
                    existing = cur.fetchone()
                    if existing:
                        _refresh_seed_row(
                            cur,
                            existing["visit_id"],
                            tech,
                            clock_in,
                            clock_out,
                            notes,
                            timesheet_metadata,
                            duration_hours,
                            payout_cents,
                            invoice_cents,
                            paid_contractor,
                            billed,
                            paid_client,
                        )
                        updated += 1
                        continue

                    location = _location_string(row)
                    client_id = _client_id_for_site(site)
                    work_order_raw = (
                        row.get("Client Work Order or Job Number (if applicable)") or ""
                    ).strip()
                    robo_match = re.search(r"RoboJob_[0-9]+", work_order_raw or location)
                    work_order = robo_match.group(0) if robo_match else (work_order_raw or None)

                    cur.execute(
                        """
                        INSERT INTO visits
                            (slack_channel_id, google_space_id, location_string, metadata_poc,
                             client_id, work_order_number, current_state, created_at, updated_at)
                        VALUES
                            (NULL, %s, %s, %s::jsonb, %s, %s, %s::visit_status, %s, %s)
                        RETURNING visit_id
                        """,
                        (
                            space_id,
                            location,
                            json.dumps(PLACEHOLDER_POC),
                            client_id,
                            work_order,
                            visit_state,
                            clock_in,
                            clock_out,
                        ),
                    )
                    visit_id = cur.fetchone()["visit_id"]

                    cur.execute(
                        """
                        INSERT INTO labor_logs
                            (visit_id, technician_identity, clock_in, clock_out,
                             extracted_findings, timesheet_metadata, is_verified,
                             paid_to_contractor, billed_to_client, paid_by_client,
                             billable_hours, amount_cents, payout_cents, invoice_cents,
                             amount_source)
                        VALUES
                            (%s, %s, %s, %s, %s, %s::jsonb, TRUE,
                             %s, %s, %s, %s, %s, %s, %s, 'explicit')
                        """,
                        (
                            visit_id,
                            tech,
                            clock_in,
                            clock_out,
                            notes,
                            json.dumps(timesheet_metadata),
                            paid_contractor,
                            billed,
                            paid_client,
                            hours,
                            payout_cents,
                            payout_cents,
                            invoice_cents,
                        ),
                    )

                    cur.execute(
                        """
                        INSERT INTO financial_ledgers
                            (visit_id, calculated_hours, invoice_cents, payout_cents,
                             approval_state, qbo_invoice_reference)
                        VALUES
                            (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            visit_id,
                            hours,
                            invoice_cents,
                            payout_cents,
                            approval_state,
                            (
                                row.get("Your Invoice Number (if applicable)") or ""
                            ).strip()
                            or None,
                        ),
                    )

                    cur.execute(
                        """
                        INSERT INTO immutable_audit_trail
                            (visit_id, execution_context, input_payload, output_receipt)
                        VALUES
                            (%s, %s, %s::jsonb, %s::jsonb)
                        """,
                        (
                            visit_id,
                            "csv_timesheet_seed",
                            json.dumps(
                                {
                                    "space_id": space_id,
                                    "technician": tech,
                                    "payout_cents": payout_cents,
                                    "implied_hourly_cents": implied_hourly,
                                }
                            ),
                            json.dumps(
                                {
                                    "visit_state": visit_state,
                                    "approval_state": approval_state,
                                }
                            ),
                        ),
                    )
                    inserted += 1

                rate_count = _upsert_technician_rates(cur, rate_samples)
        print(
            f"Inserted {inserted} visits; refreshed {updated}; "
            f"skipped {skipped} (invalid). Upserted {rate_count} technician rates."
        )
        return inserted
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--database-url", default=DEFAULT_DATABASE_URL)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.csv.exists():
        print(f"CSV not found: {args.csv}", file=sys.stderr)
        sys.exit(1)
    seed(args.database_url, args.csv, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
