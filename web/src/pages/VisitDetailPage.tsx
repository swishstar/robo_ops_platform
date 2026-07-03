import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { TimesheetPanel } from "../components/TimesheetPanel";
import { WebChat } from "../components/WebChat";

export function VisitDetailPage() {
  const { visitId } = useParams<{ visitId: string }>();

  const { data, isLoading, error } = useQuery({
    queryKey: ["visit", visitId],
    queryFn: () => api.getVisit(visitId!),
    enabled: !!visitId,
  });

  if (isLoading) return <p>Loading…</p>;
  if (error || !data) return <p className="error">{(error as Error)?.message ?? "Not found"}</p>;

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

      <TimesheetPanel visitId={visitId!} visit={data} />

      <WebChat visitId={visitId} />
    </section>
  );
}
