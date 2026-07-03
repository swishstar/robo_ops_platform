import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { WebChat } from "../components/WebChat";

export function VisitDetailPage() {
  const { visitId } = useParams<{ visitId: string }>();
  const qc = useQueryClient();
  const [findings, setFindings] = useState("");
  const [clockIn, setClockIn] = useState("");
  const [clockOut, setClockOut] = useState("");

  const { data, isLoading, error } = useQuery({
    queryKey: ["visit", visitId],
    queryFn: () => api.getVisit(visitId!),
    enabled: !!visitId,
  });

  const clockInMut = useMutation({
    mutationFn: () => api.clockIn(visitId!),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["visit", visitId] }),
  });

  const signoffMut = useMutation({
    mutationFn: () =>
      api.signoff(visitId!, {
        clock_in: new Date(clockIn).toISOString(),
        clock_out: new Date(clockOut).toISOString(),
        findings,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["visit", visitId] }),
  });

  if (isLoading) return <p>Loading…</p>;
  if (error || !data) return <p className="error">{(error as Error)?.message ?? "Not found"}</p>;

  const activeLog = data.labor_logs.find((l) => l.clock_in && !l.clock_out);
  const canClockIn = ["initiated", "active"].includes(data.current_state) && !activeLog;
  const canSignoff = data.current_state === "active" && !!activeLog;

  return (
    <section>
      <Link to="/">&larr; Visits</Link>
      <h1>{data.location_string}</h1>
      <p>
        State: <span className={`badge state-${data.current_state}`}>{data.current_state}</span>
      </p>
      <p>POC: {data.metadata_poc.name} — {data.metadata_poc.phone}</p>
      {data.slack_channel_id && <p>Slack: {data.slack_channel_id} (client/external)</p>}
      {data.google_space_id && <p>Google Chat: {data.google_space_id} (internal)</p>}

      <div className="panel">
        <h2>Timekeeping</h2>
        {activeLog && (
          <p>Clocked in: {new Date(activeLog.clock_in!).toLocaleString()}</p>
        )}
        {canClockIn && (
          <button type="button" onClick={() => clockInMut.mutate()} disabled={clockInMut.isPending}>
            Clock In
          </button>
        )}
        {canSignoff && (
          <div className="signoff-form">
            <label>
              Clock in (confirm)
              <input type="datetime-local" value={clockIn} onChange={(e) => setClockIn(e.target.value)} />
            </label>
            <label>
              Clock out
              <input type="datetime-local" value={clockOut} onChange={(e) => setClockOut(e.target.value)} />
            </label>
            <label>
              Findings
              <textarea value={findings} onChange={(e) => setFindings(e.target.value)} rows={4} />
            </label>
            <button
              type="button"
              onClick={() => signoffMut.mutate()}
              disabled={signoffMut.isPending || findings.length < 8}
            >
              Sign Off
            </button>
          </div>
        )}
        {(clockInMut.error || signoffMut.error) && (
          <p className="error">
            {((clockInMut.error ?? signoffMut.error) as Error).message}
          </p>
        )}
      </div>

      <WebChat visitId={visitId} />
    </section>
  );
}
