import { useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, TimesheetRow } from "../api/client";
import { FinanceNav } from "../components/FinanceNav";
import {
  PAYMENT_FLAG_FIELDS,
  PaymentFlagEditor,
  PaymentFlagKey,
  PaymentFlagValues,
} from "../components/PaymentFlags";
import { formatBillableHours } from "../constants/timesheet";

function formatCents(cents: number | null | undefined) {
  if (cents == null) return "—";
  return `$${(cents / 100).toFixed(2)}`;
}

export function FinanceProgressPage() {
  const qc = useQueryClient();
  const pendingFlags = useRef(new Map<string, PaymentFlagValues>());

  const listQuery = useQuery({
    queryKey: ["timesheets", "finance-progress"],
    queryFn: () => api.listTimesheets(),
  });

  const flagMut = useMutation({
    mutationFn: (vars: { logId: string; flags: PaymentFlagValues }) =>
      api.updateTimesheetFlags(vars.logId, vars.flags),
    onSuccess: (_data, vars) => {
      const pending = pendingFlags.current.get(vars.logId);
      if (pending && JSON.stringify(pending) === JSON.stringify(vars.flags)) {
        pendingFlags.current.delete(vars.logId);
      }
      qc.invalidateQueries({ queryKey: ["timesheets"] });
    },
  });

  function updateFlag(row: TimesheetRow, key: PaymentFlagKey, value: boolean | null) {
    const current = pendingFlags.current.get(row.log_id) ?? {
      billed_to_client: row.billed_to_client,
      paid_by_client: row.paid_by_client,
      paid_to_contractor: row.paid_to_contractor,
    };
    const next = { ...current, [key]: value };
    pendingFlags.current.set(row.log_id, next);
    flagMut.mutate({ logId: row.log_id, flags: next });
  }

  const rows = listQuery.data?.timesheets ?? [];

  return (
    <section className="finance-progress-page">
      <FinanceNav />
      <div className="page-header">
        <h1>Payment progress</h1>
      </div>
      <p className="hint">
        Set billed, paid by the client, and paid to the contractor. Technicians can see these on
        Timesheets and cannot change them.
      </p>

      {listQuery.isLoading && <p>Loading…</p>}
      {listQuery.error && <p className="error">{(listQuery.error as Error).message}</p>}
      {flagMut.error && <p className="error">{(flagMut.error as Error).message}</p>}

      <div className="table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              <th>Technician</th>
              <th>Site</th>
              <th>Job</th>
              <th>Hours</th>
              <th>Amount</th>
              {PAYMENT_FLAG_FIELDS.map(([, label]) => (
                <th key={label}>{label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const pending = pendingFlags.current.get(row.log_id);
              const flags = pending ?? row;
              const busy = flagMut.isPending && flagMut.variables?.logId === row.log_id;
              return (
                <tr key={row.log_id}>
                  <td>{row.technician_identity}</td>
                  <td>
                    <Link to={`/visits/${row.visit_id}`}>{row.location_string}</Link>
                  </td>
                  <td className="mono">{row.work_order_number || "—"}</td>
                  <td className="num">
                    {row.billable_hours != null
                      ? formatBillableHours(Number(row.billable_hours))
                      : "—"}
                  </td>
                  <td className="num">{formatCents(row.amount_cents)}</td>
                  {PAYMENT_FLAG_FIELDS.map(([key, label]) => (
                    <td key={key}>
                      <PaymentFlagEditor
                        label={label}
                        value={flags[key]}
                        disabled={busy}
                        onChange={(next) => updateFlag(row, key, next)}
                      />
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {!listQuery.isLoading && rows.length === 0 && (
        <p className="empty-state">No timesheet rows yet.</p>
      )}
    </section>
  );
}
