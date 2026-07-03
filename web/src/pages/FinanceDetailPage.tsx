import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { WebChat } from "../components/WebChat";

function formatCents(cents: number) {
  return `$${(cents / 100).toFixed(2)}`;
}

export function FinanceDetailPage() {
  const { ledgerId } = useParams<{ ledgerId: string }>();
  const qc = useQueryClient();
  const [rejectReason, setRejectReason] = useState("");

  const { data, isLoading, error } = useQuery({
    queryKey: ["finance-ledger", ledgerId],
    queryFn: () => api.financeLedger(ledgerId!),
    enabled: !!ledgerId,
  });

  const approveMut = useMutation({
    mutationFn: (action: "approve" | "reject") =>
      api.financeApprove({
        approval_token: data!.approval_token!,
        action,
        rejection_reason: action === "reject" ? rejectReason : undefined,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["finance-pending"] });
      qc.invalidateQueries({ queryKey: ["finance-ledger", ledgerId] });
    },
  });

  if (isLoading) return <p>Loading…</p>;
  if (error || !data) return <p className="error">{(error as Error)?.message ?? "Not found"}</p>;

  const pending = data.approval_state === "pending_review";

  return (
    <section>
      <Link to="/finance">&larr; Queue</Link>
      <h1>{data.location_string}</h1>
      <p>State: {data.approval_state}</p>
      <dl className="detail-grid">
        <dt>Hours</dt>
        <dd>{data.calculated_hours}</dd>
        <dt>Invoice</dt>
        <dd>{formatCents(data.invoice_cents)}</dd>
        <dt>Contractor payout</dt>
        <dd>{formatCents(data.payout_cents)}</dd>
        <dt>Technician</dt>
        <dd>{data.technician_identity}</dd>
        <dt>Findings</dt>
        <dd>{data.extracted_findings}</dd>
      </dl>

      {pending && data.approval_token && (
        <div className="panel actions">
          <button
            type="button"
            className="primary"
            onClick={() => approveMut.mutate("approve")}
            disabled={approveMut.isPending}
          >
            Approve Payout
          </button>
          <label>
            Rejection reason
            <input value={rejectReason} onChange={(e) => setRejectReason(e.target.value)} />
          </label>
          <button
            type="button"
            className="danger"
            onClick={() => approveMut.mutate("reject")}
            disabled={approveMut.isPending || rejectReason.length < 5}
          >
            Reject
          </button>
        </div>
      )}
      {approveMut.error && <p className="error">{(approveMut.error as Error).message}</p>}

      <WebChat visitId={data.visit_id} />
    </section>
  );
}
