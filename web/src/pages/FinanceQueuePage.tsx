import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";

function formatCents(cents: number) {
  return `$${(cents / 100).toFixed(2)}`;
}

const STATUS_OPTIONS = [
  { value: "pending_review", label: "Pending Review" },
  { value: "approved", label: "Approved" },
  { value: "rejected", label: "Rejected" },
  { value: "", label: "All" },
];

export function FinanceQueuePage() {
  const [statusFilter, setStatusFilter] = useState("pending_review");

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["finance-ledgers", statusFilter],
    queryFn: () =>
      api.financeLedgers({
        approval_state: statusFilter || undefined,
      }),
  });

  return (
    <section>
      <div className="page-header">
        <h1>Finance</h1>
        <div className="header-actions">
          <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
            {STATUS_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
          <button type="button" onClick={() => refetch()}>
            Refresh
          </button>
        </div>
      </div>

      {isLoading && <p>Loading…</p>}
      {error && <p className="error">{(error as Error).message}</p>}

      <table className="data-table">
        <thead>
          <tr>
            <th>Location</th>
            <th>Status</th>
            <th>Technician</th>
            <th>Hours</th>
            <th>Invoice</th>
            <th>Payout</th>
            <th>QBO Ref</th>
            <th>Date</th>
          </tr>
        </thead>
        <tbody>
          {(data?.ledgers ?? []).map((row) => (
            <tr key={row.ledger_id}>
              <td>
                <Link to={`/finance/${row.ledger_id}`}>{row.location_string}</Link>
              </td>
              <td>
                <span className={`badge state-${row.approval_state}`}>{row.approval_state}</span>
              </td>
              <td>{row.technician_identity ?? "—"}</td>
              <td>{row.calculated_hours}</td>
              <td>{formatCents(row.invoice_cents)}</td>
              <td>{formatCents(row.payout_cents)}</td>
              <td>{row.qbo_invoice_reference ?? "—"}</td>
              <td>{row.created_at ? new Date(row.created_at).toLocaleDateString() : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {!isLoading && !data?.ledgers?.length && <p>No records found.</p>}
    </section>
  );
}
