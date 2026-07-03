import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";

export function NewVisitPage() {
  const navigate = useNavigate();
  const [location, setLocation] = useState("");
  const [pocName, setPocName] = useState("");
  const [pocPhone, setPocPhone] = useState("");
  const [pocEmail, setPocEmail] = useState("");
  const [slackChannel, setSlackChannel] = useState("");

  const createMut = useMutation({
    mutationFn: () =>
      api.createVisit({
        location_string: location,
        metadata_poc: { name: pocName, phone: pocPhone, email: pocEmail },
        slack_channel_id: slackChannel || undefined,
      }),
    onSuccess: (data) => navigate(`/visits/${data.visit_id}`),
  });

  const valid =
    location.length >= 3 &&
    pocName.length >= 2 &&
    pocPhone.length >= 7 &&
    pocEmail.includes("@");

  return (
    <section>
      <Link to="/">&larr; Visits</Link>
      <h1>New Service Request</h1>

      <div className="panel">
        <label>
          Location
          <input
            value={location}
            onChange={(e) => setLocation(e.target.value)}
            placeholder="e.g. 1234 Industrial Pkwy, Suite 200"
          />
        </label>

        <fieldset>
          <legend>Point of Contact</legend>
          <label>
            Name
            <input value={pocName} onChange={(e) => setPocName(e.target.value)} />
          </label>
          <label>
            Phone
            <input value={pocPhone} onChange={(e) => setPocPhone(e.target.value)} type="tel" />
          </label>
          <label>
            Email
            <input value={pocEmail} onChange={(e) => setPocEmail(e.target.value)} type="email" />
          </label>
        </fieldset>

        <label>
          Slack channel ID (optional)
          <input
            value={slackChannel}
            onChange={(e) => setSlackChannel(e.target.value)}
            placeholder="e.g. C0123456789"
          />
        </label>

        <button
          type="button"
          className="primary"
          onClick={() => createMut.mutate()}
          disabled={!valid || createMut.isPending}
        >
          {createMut.isPending ? "Creating…" : "Create Visit"}
        </button>

        {createMut.error && (
          <p className="error">{(createMut.error as Error).message}</p>
        )}
      </div>
    </section>
  );
}
