import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { api, getStoredUser } from "../api/client";
import { TimesheetPanel } from "../components/TimesheetPanel";
import { WebChat } from "../components/WebChat";

export function VisitDetailPage() {
  const { visitId } = useParams<{ visitId: string }>();
  const user = getStoredUser();
  const isAdmin = user.role === "admin";
  const queryClient = useQueryClient();

  const { data, isLoading, error } = useQuery({
    queryKey: ["visit", visitId],
    queryFn: () => api.getVisit(visitId!),
    enabled: !!visitId,
  });

  const clientsQuery = useQuery({
    queryKey: ["clients"],
    queryFn: () => api.listClients(),
    enabled: isAdmin,
  });

  const [location, setLocation] = useState("");
  const [workOrder, setWorkOrder] = useState("");
  const [clientId, setClientId] = useState("");
  const [pocName, setPocName] = useState("");
  const [pocPhone, setPocPhone] = useState("");
  const [pocEmail, setPocEmail] = useState("");
  const [slackChannel, setSlackChannel] = useState("");
  const [savedMsg, setSavedMsg] = useState<string | null>(null);

  useEffect(() => {
    if (!data) return;
    setLocation(data.location_string || "");
    setWorkOrder(data.work_order_number || "");
    setClientId(data.client_id || "");
    setPocName(data.metadata_poc?.name || "");
    setPocPhone(data.metadata_poc?.phone || "");
    setPocEmail(data.metadata_poc?.email || "");
    setSlackChannel(data.slack_channel_id || "");
  }, [data]);

  const saveMut = useMutation({
    mutationFn: () =>
      api.updateVisit(visitId!, {
        location_string: location,
        work_order_number: workOrder,
        client_id: clientId || undefined,
        metadata_poc: { name: pocName, phone: pocPhone, email: pocEmail },
        slack_channel_id: slackChannel,
        clear_slack_channel: !slackChannel.trim(),
      }),
    onSuccess: () => {
      setSavedMsg("Saved.");
      queryClient.invalidateQueries({ queryKey: ["visit", visitId] });
      queryClient.invalidateQueries({ queryKey: ["visits"] });
    },
    onError: (err: Error) => setSavedMsg(err.message),
  });

  if (isLoading) return <p>Loading…</p>;
  if (error || !data) return <p className="error">{(error as Error)?.message ?? "Not found"}</p>;

  return (
    <section>
      <Link to="/">&larr; Visits</Link>
      <h1>{data.location_string}</h1>
      <p>
        {data.work_order_number && (
          <>
            Job ID: <strong className="mono">{data.work_order_number}</strong>
            {" · "}
          </>
        )}
        State: <span className={`badge state-${data.current_state}`}>{data.current_state}</span>
        {data.client_id && (
          <>
            {" "}
            · Client: <strong>{data.client_id}</strong>
          </>
        )}
      </p>
      <p>
        POC: {data.metadata_poc.name} — {data.metadata_poc.phone}
      </p>
      {data.slack_channel_id && <p>Slack: {data.slack_channel_id} (client/external)</p>}
      {data.google_space_id && <p>Google Chat: {data.google_space_id} (internal)</p>}

      {isAdmin && (
        <div className="panel">
          <h2>Edit visit (admin)</h2>
          <label>
            Job ID (RoboJob)
            <input
              value={workOrder}
              onChange={(e) => setWorkOrder(e.target.value)}
              placeholder="e.g. RoboJob_00126"
            />
          </label>
          <label>
            Location
            <input value={location} onChange={(e) => setLocation(e.target.value)} />
          </label>
          <label>
            Client
            <select value={clientId} onChange={(e) => setClientId(e.target.value)}>
              {(clientsQuery.data?.clients ?? [{ id: "chef", display_name: "Chef" }]).map((c) => (
                <option key={c.id} value={c.id}>
                  {c.display_name}
                </option>
              ))}
            </select>
          </label>
          <fieldset>
            <legend>Point of Contact</legend>
            <label>
              Name
              <input value={pocName} onChange={(e) => setPocName(e.target.value)} />
            </label>
            <label>
              Phone
              <input value={pocPhone} onChange={(e) => setPocPhone(e.target.value)} />
            </label>
            <label>
              Email
              <input value={pocEmail} onChange={(e) => setPocEmail(e.target.value)} />
            </label>
          </fieldset>
          <label>
            Slack channel ID
            <input
              value={slackChannel}
              onChange={(e) => setSlackChannel(e.target.value)}
              placeholder="optional"
            />
          </label>
          <div className="header-actions">
            <button
              type="button"
              className="btn-link primary"
              disabled={saveMut.isPending || location.trim().length < 3}
              onClick={() => {
                setSavedMsg(null);
                saveMut.mutate();
              }}
            >
              {saveMut.isPending ? "Saving…" : "Save changes"}
            </button>
            {savedMsg && <span className={saveMut.isError ? "error" : "hint"}>{savedMsg}</span>}
          </div>
        </div>
      )}

      <TimesheetPanel visitId={visitId!} visit={data} />

      <WebChat visitId={visitId} />
    </section>
  );
}
