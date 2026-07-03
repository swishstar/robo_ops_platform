import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";

function formatCents(cents: number | null | undefined) {
  if (cents == null) return "—";
  return `$${(cents / 100).toFixed(2)}`;
}

const STATE_OPTIONS = [
  { value: "", label: "Active / Upcoming" },
  { value: "initiated", label: "Initiated" },
  { value: "active", label: "Active" },
  { value: "pending_approval", label: "Pending Approval" },
  { value: "completed", label: "Completed" },
  { value: "failed", label: "Failed" },
  { value: "__all__", label: "All" },
];

export function VisitsPage() {
  const [stateFilter, setStateFilter] = useState("");

  const includeCompleted = stateFilter === "__all__" || stateFilter === "completed" || stateFilter === "failed";
  const effectiveState = stateFilter === "__all__" ? undefined : stateFilter || undefined;

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["visits", effectiveState, includeCompleted],
    queryFn: () =>
      api.listVisits({
        state: effectiveState,
        include_completed: includeCompleted,
      }),
  });

  return (
    <section>
      <div className="page-header">
        <h1>Visits</h1>
        <div className="header-actions">
          <select value={stateFilter} onChange={(e) => setStateFilter(e.target.value)}>
            {STATE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
          <button type="button" onClick={() => refetch()}>
            Refresh
          </button>
          <Link to="/visits/new" className="btn-link primary">
            + New Service Request
          </Link>
        </div>
      </div>

      {isLoading && <p>Loading visits…</p>}
      {error && <p className="error">{(error as Error).message}</p>}

      <table className="data-table">
        <thead>
          <tr>
            <th>Location</th>
            <th>State</th>
            <th>Technician</th>
            <th>Pay Status</th>
            <th>Payout</th>
            <th>Created</th>
          </tr>
        </thead>
        <tbody>
          {(data?.visits ?? []).map((v) => (
            <tr key={v.visit_id}>
              <td>
                <Link to={`/visits/${v.visit_id}`}>{v.location_string}</Link>
              </td>
              <td>
                <span className={`badge state-${v.current_state}`}>{v.current_state}</span>
              </td>
              <td>{v.technician_identity ?? "—"}</td>
              <td>{v.pay_status ?? "—"}</td>
              <td>{formatCents(v.payout_cents)}</td>
              <td>{new Date(v.created_at).toLocaleDateString()}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {!isLoading && !data?.visits?.length && <p>No visits found.</p>}
    </section>
  );
}
