import { useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, getStoredUser, TimesheetRow } from "../api/client";
import { amountSourceLabel, formatBillableHours } from "../constants/timesheet";

function formatCents(cents: number | null | undefined) {
  if (cents == null) return "—";
  return `$${(cents / 100).toFixed(2)}`;
}

function isoDate(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function thisWeekRange(): { from: string; to: string } {
  const now = new Date();
  const mondayOffset = (now.getDay() + 6) % 7;
  const monday = new Date(now);
  monday.setDate(now.getDate() - mondayOffset);
  const sunday = new Date(monday);
  sunday.setDate(monday.getDate() + 6);
  return { from: isoDate(monday), to: isoDate(sunday) };
}

function flagToSelect(value: boolean | null | undefined): string {
  if (value === true) return "true";
  if (value === false) return "false";
  return "";
}

function selectToFlag(value: string): boolean | null {
  if (value === "true") return true;
  if (value === "false") return false;
  return null;
}

export function TimesheetsPage() {
  const user = getStoredUser();
  const isTech = user.role === "technician";
  const canAssignTech = user.role === "admin" || user.role === "finance_manager";
  const qc = useQueryClient();

  const [technician, setTechnician] = useState("");
  const [client, setClient] = useState("");
  const [workOrder, setWorkOrder] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  const [visitQuery, setVisitQuery] = useState("");
  const [visitId, setVisitId] = useState("");
  const [techName, setTechName] = useState("");
  const [techEmail, setTechEmail] = useState("");
  const [clockIn, setClockIn] = useState("");
  const [clockOut, setClockOut] = useState("");
  const [notes, setNotes] = useState("");
  const [amountDollars, setAmountDollars] = useState("");
  const [formError, setFormError] = useState("");

  const filters = {
    technician: technician.trim() || undefined,
    client: client.trim() || undefined,
    work_order: workOrder.trim() || undefined,
    date_from: dateFrom || undefined,
    date_to: dateTo || undefined,
  };

  const listQuery = useQuery({
    queryKey: ["timesheets", user.role, user.email, filters],
    queryFn: () => api.listTimesheets(filters),
  });

  const visitsQuery = useQuery({
    queryKey: ["visits", "timesheet-picker", user.role, user.email],
    queryFn: () => api.listVisits({ include_completed: true }),
  });

  const visitOptions = useMemo(() => {
    const q = visitQuery.trim().toLowerCase();
    return (visitsQuery.data?.visits ?? []).filter((visit) => {
      if (!q) return true;
      return (
        visit.location_string.toLowerCase().includes(q) ||
        (visit.work_order_number || "").toLowerCase().includes(q) ||
        visit.visit_id.toLowerCase().includes(q)
      );
    });
  }, [visitQuery, visitsQuery.data?.visits]);

  const createMut = useMutation({
    mutationFn: () => {
      const rawAmount = amountDollars.trim().replace(/[$,]/g, "");
      let explicitAmountCents: number | undefined;
      if (rawAmount) {
        const dollars = Number(rawAmount);
        if (!Number.isFinite(dollars) || dollars < 0) {
          throw new Error("Amount must be a positive number of dollars.");
        }
        explicitAmountCents = Math.round(dollars * 100);
      }
      return api.createTimesheet({
        visit_id: visitId,
        technician_identity: canAssignTech && techEmail.trim() ? techEmail.trim() : undefined,
        technician_name: canAssignTech && techName.trim() ? techName.trim() : undefined,
        clock_in: new Date(clockIn).toISOString(),
        clock_out: new Date(clockOut).toISOString(),
        findings: notes,
        explicit_amount_cents: explicitAmountCents,
      });
    },
    onSuccess: () => {
      setFormError("");
      setNotes("");
      setAmountDollars("");
      qc.invalidateQueries({ queryKey: ["timesheets"] });
      qc.invalidateQueries({ queryKey: ["visit", visitId] });
    },
    onError: (err: Error) => setFormError(err.message),
  });

  type PaymentFlags = {
    paid_to_contractor: boolean | null;
    billed_to_client: boolean | null;
    paid_by_client: boolean | null;
  };
  const pendingFlags = useRef(new Map<string, PaymentFlags>());

  const flagMut = useMutation({
    mutationFn: (vars: { logId: string; flags: PaymentFlags }) =>
      api.updateTimesheetFlags(vars.logId, vars.flags),
    onSuccess: (_data, vars) => {
      const pending = pendingFlags.current.get(vars.logId);
      if (pending && JSON.stringify(pending) === JSON.stringify(vars.flags)) {
        pendingFlags.current.delete(vars.logId);
      }
      qc.invalidateQueries({ queryKey: ["timesheets"] });
    },
  });

  function updateFlag(row: TimesheetRow, key: keyof PaymentFlags, value: string) {
    const current = pendingFlags.current.get(row.log_id) ?? {
      paid_to_contractor: row.paid_to_contractor,
      billed_to_client: row.billed_to_client,
      paid_by_client: row.paid_by_client,
    };
    const next = { ...current, [key]: selectToFlag(value) };
    pendingFlags.current.set(row.log_id, next);
    flagMut.mutate({ logId: row.log_id, flags: next });
  }

  const rows = listQuery.data?.timesheets ?? [];
  const hoursPreview = useMemo(() => {
    if (!clockIn || !clockOut) return 0;
    const start = new Date(clockIn).getTime();
    const end = new Date(clockOut).getTime();
    if (Number.isNaN(start) || Number.isNaN(end) || end <= start) return 0;
    const minutes = (end - start) / 60_000;
    return Math.round((Math.ceil(minutes / 15) * 15) / 60 * 100) / 100;
  }, [clockIn, clockOut]);

  const canSubmit = !!visitId && !!clockIn && !!clockOut && hoursPreview > 0 && !createMut.isPending;

  return (
    <section className="timesheet-page">
      <div className="page-header">
        <h1>{isTech ? "My Timesheets" : "Timesheets"}</h1>
      </div>
      <p className="hint">
        One row per technician on a job. Log time after the visit — clock-in is not required.
        {canAssignTech ? " Enter another technician to add them to an existing job." : ""}
      </p>

      <form
        className="panel"
        onSubmit={(e) => {
          e.preventDefault();
          setFormError("");
          if (canSubmit) createMut.mutate();
        }}
      >
        <h2>Add timesheet row</h2>
        <div className="form-grid">
          <label>
            Find visit
            <input
              value={visitQuery}
              onChange={(e) => setVisitQuery(e.target.value)}
              placeholder="Site, job, or id"
            />
          </label>
          <label>
            Visit
            <select value={visitId} onChange={(e) => setVisitId(e.target.value)} required>
              <option value="">Select a job…</option>
              {visitOptions.map((visit) => (
                <option key={visit.visit_id} value={visit.visit_id}>
                  {(visit.work_order_number || "No job")} — {visit.location_string}
                </option>
              ))}
            </select>
          </label>
          {canAssignTech && (
            <>
              <label>
                Technician name
                <input value={techName} onChange={(e) => setTechName(e.target.value)} />
              </label>
              <label>
                Technician email
                <input
                  type="email"
                  value={techEmail}
                  onChange={(e) => setTechEmail(e.target.value)}
                  placeholder="Leave blank to log yourself"
                />
              </label>
            </>
          )}
          <label>
            Arrival
            <input
              type="datetime-local"
              value={clockIn}
              onChange={(e) => setClockIn(e.target.value)}
              required
            />
          </label>
          <label>
            Departure
            <input
              type="datetime-local"
              value={clockOut}
              onChange={(e) => setClockOut(e.target.value)}
              required
            />
          </label>
          <label>
            Hours
            <input type="text" value={hoursPreview ? formatBillableHours(hoursPreview) : ""} readOnly />
          </label>
          <label>
            Amount if no rate ($)
            <input
              value={amountDollars}
              onChange={(e) => setAmountDollars(e.target.value)}
              inputMode="decimal"
              placeholder="Optional"
            />
          </label>
        </div>
        <label>
          Notes
          <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={3} />
        </label>
        <button type="submit" className="primary" disabled={!canSubmit}>
          {createMut.isPending ? "Saving…" : "Add row"}
        </button>
        {createMut.data && (
          <p className="hint">
            {createMut.data.message} Logged {formatBillableHours(createMut.data.billable_hours)} ·{" "}
            {formatCents(createMut.data.amount_cents)}.
          </p>
        )}
        {formError && <p className="error">{formError}</p>}
      </form>

      <div className="filter-bar">
        {!isTech && (
          <label>
            Technician
            <input
              value={technician}
              onChange={(e) => setTechnician(e.target.value)}
              placeholder="Name or email"
            />
          </label>
        )}
        <label>
          Client / site
          <input value={client} onChange={(e) => setClient(e.target.value)} placeholder="Bonduelle" />
        </label>
        <label>
          Job
          <input
            value={workOrder}
            onChange={(e) => setWorkOrder(e.target.value)}
            placeholder="Work order"
          />
        </label>
        <label>
          From
          <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
        </label>
        <label>
          To
          <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
        </label>
        <button
          type="button"
          onClick={() => {
            const week = thisWeekRange();
            setDateFrom(week.from);
            setDateTo(week.to);
          }}
        >
          This week
        </button>
        <button
          type="button"
          onClick={() => {
            setTechnician("");
            setClient("");
            setWorkOrder("");
            setDateFrom("");
            setDateTo("");
          }}
        >
          Clear
        </button>
      </div>

      {listQuery.isLoading && <p>Loading timesheets…</p>}
      {listQuery.error && <p className="error">{(listQuery.error as Error).message}</p>}
      {listQuery.data?.truncated && (
        <p className="hint">Showing the first 1000 matching rows.</p>
      )}
      {flagMut.error && <p className="error">{(flagMut.error as Error).message}</p>}

      <div className="table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              <th>Technician</th>
              <th>Site</th>
              <th>Job</th>
              <th>Arrival</th>
              <th>Departure</th>
              <th>Hours</th>
              <th>Amount</th>
              <th>Notes</th>
              <th>Paid to contractor</th>
              <th>Billed to client</th>
              <th>Paid by client</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.log_id}>
                <td>{row.technician_identity}</td>
                <td>
                  <Link to={`/visits/${row.visit_id}`}>{row.location_string}</Link>
                  {row.client_id ? <div className="cell-sub">{row.client_id}</div> : null}
                </td>
                <td className="mono">{row.work_order_number || "—"}</td>
                <td>{row.clock_in ? new Date(row.clock_in).toLocaleString() : "—"}</td>
                <td>{row.clock_out ? new Date(row.clock_out).toLocaleString() : "—"}</td>
                <td>
                  {row.billable_hours != null ? formatBillableHours(Number(row.billable_hours)) : "—"}
                </td>
                <td>
                  {formatCents(row.amount_cents)}
                  <span className="amount-source">
                    {amountSourceLabel(row.amount_source, row.rate_payout_cents_per_hour)}
                  </span>
                </td>
                <td className="notes-cell" title={row.extracted_findings || ""}>
                  {row.extracted_findings || "—"}
                </td>
                {(
                  [
                    ["paid_to_contractor", "Paid to contractor"],
                    ["billed_to_client", "Billed to client"],
                    ["paid_by_client", "Paid by client"],
                  ] as const
                ).map(([key, label]) => (
                  <td key={key}>
                    <select
                      aria-label={label}
                      className="flag-select"
                      value={flagToSelect(row[key])}
                      disabled={flagMut.isPending && flagMut.variables?.logId === row.log_id}
                      onChange={(e) => updateFlag(row, key, e.target.value)}
                    >
                      <option value="">—</option>
                      <option value="true">Yes</option>
                      <option value="false">No</option>
                    </select>
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!listQuery.isLoading && rows.length === 0 && (
        <p className="empty-state">No timesheet rows match these filters.</p>
      )}
    </section>
  );
}
