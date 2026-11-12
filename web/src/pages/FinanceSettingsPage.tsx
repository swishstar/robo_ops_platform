import { FormEvent, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, TechnicianRate } from "../api/client";
import { FinanceNav } from "../components/FinanceNav";

function dollarsToCents(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const dollars = Number(trimmed);
  if (!Number.isFinite(dollars) || dollars < 0) return null;
  return Math.round(dollars * 100);
}

function centsToDollars(cents: number): string {
  return (cents / 100).toFixed(2);
}

export function FinanceSettingsPage() {
  const qc = useQueryClient();
  const ratesQuery = useQuery({
    queryKey: ["technician-rates"],
    queryFn: () => api.listTechnicianRates(),
  });

  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [payout, setPayout] = useState("");
  const [invoice, setInvoice] = useState("");
  const [formError, setFormError] = useState("");

  const saveMut = useMutation({
    mutationFn: api.upsertTechnicianRate,
    onSuccess: () => {
      setFormError("");
      setEmail("");
      setName("");
      setPayout("");
      setInvoice("");
      qc.invalidateQueries({ queryKey: ["technician-rates"] });
      qc.invalidateQueries({ queryKey: ["timesheets"] });
    },
    onError: (err: Error) => setFormError(err.message),
  });

  function submit(event: FormEvent, body: {
    technician_email: string;
    technician_name?: string;
    payout_cents_per_hour: number;
    invoice_cents_per_hour: number;
  }) {
    event.preventDefault();
    saveMut.mutate(body);
  }

  function saveNew(event: FormEvent) {
    const payoutCents = dollarsToCents(payout);
    const invoiceCents = dollarsToCents(invoice);
    if (!email.trim() || payoutCents == null || invoiceCents == null) {
      setFormError("Email, payout rate, and invoice rate are required.");
      return;
    }
    submit(event, {
      technician_email: email.trim(),
      technician_name: name.trim() || undefined,
      payout_cents_per_hour: payoutCents,
      invoice_cents_per_hour: invoiceCents,
    });
  }

  return (
    <section>
      <FinanceNav />
      <div className="page-header">
        <h1>Rate settings</h1>
      </div>
      <p className="hint">
        Payout is what the contractor is paid per hour. Invoice is what the client is billed per
        hour. New timesheet rows use the rate on file for that email.
      </p>

      <form className="panel" onSubmit={saveNew}>
        <h2>Add or replace a rate</h2>
        <div className="form-grid">
          <label>
            Email
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </label>
          <label>
            Name
            <input value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <label>
            Payout $ / hour
            <input
              inputMode="decimal"
              value={payout}
              onChange={(e) => setPayout(e.target.value)}
              required
            />
          </label>
          <label>
            Invoice $ / hour
            <input
              inputMode="decimal"
              value={invoice}
              onChange={(e) => setInvoice(e.target.value)}
              required
            />
          </label>
        </div>
        <button type="submit" className="primary" disabled={saveMut.isPending}>
          {saveMut.isPending ? "Saving…" : "Save rate"}
        </button>
        {formError && <p className="error">{formError}</p>}
      </form>

      {ratesQuery.isLoading && <p>Loading rates…</p>}
      {ratesQuery.error && <p className="error">{(ratesQuery.error as Error).message}</p>}

      <div className="table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Email</th>
              <th>Payout / hour</th>
              <th>Invoice / hour</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {(ratesQuery.data?.rates ?? []).map((rate) => (
              <RateRow key={rate.technician_email} rate={rate} onSave={saveMut.mutate} busy={saveMut.isPending} />
            ))}
          </tbody>
        </table>
      </div>
      {!ratesQuery.isLoading && !(ratesQuery.data?.rates ?? []).length && (
        <p className="empty-state">No technician rates yet.</p>
      )}
    </section>
  );
}

function RateRow({
  rate,
  onSave,
  busy,
}: {
  rate: TechnicianRate;
  onSave: (body: {
    technician_email: string;
    technician_name?: string;
    payout_cents_per_hour: number;
    invoice_cents_per_hour: number;
  }) => void;
  busy: boolean;
}) {
  const [name, setName] = useState(rate.technician_name ?? "");
  const [payout, setPayout] = useState(centsToDollars(rate.payout_cents_per_hour));
  const [invoice, setInvoice] = useState(centsToDollars(rate.invoice_cents_per_hour));
  const [rowError, setRowError] = useState("");

  return (
    <tr>
      <td>
        <input value={name} onChange={(e) => setName(e.target.value)} aria-label="Name" />
      </td>
      <td className="mono">{rate.technician_email}</td>
      <td>
        <input
          className="rate-input"
          inputMode="decimal"
          value={payout}
          onChange={(e) => setPayout(e.target.value)}
          aria-label="Payout per hour"
        />
      </td>
      <td>
        <input
          className="rate-input"
          inputMode="decimal"
          value={invoice}
          onChange={(e) => setInvoice(e.target.value)}
          aria-label="Invoice per hour"
        />
      </td>
      <td>
        <button
          type="button"
          disabled={busy}
          onClick={() => {
            const payoutCents = dollarsToCents(payout);
            const invoiceCents = dollarsToCents(invoice);
            if (payoutCents == null || invoiceCents == null) {
              setRowError("Enter dollar amounts.");
              return;
            }
            setRowError("");
            onSave({
              technician_email: rate.technician_email,
              technician_name: name.trim() || undefined,
              payout_cents_per_hour: payoutCents,
              invoice_cents_per_hour: invoiceCents,
            });
          }}
        >
          Update
        </button>
        {rowError && <span className="error cell-sub">{rowError}</span>}
      </td>
    </tr>
  );
}
