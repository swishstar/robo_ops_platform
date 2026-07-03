import { useEffect, useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, VisitDetail } from "../api/client";
import { getStoredUser } from "../api/client";
import {
  ROBOT_PLATFORMS,
  SERVICE_TYPES,
  type RobotPlatform,
  type ServiceType,
  type TimesheetMetadata,
} from "../constants/timesheet";

function toDatetimeLocalValue(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function todayDateValue(): string {
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function computeBillableHours(clockIn: string, clockOut: string, breakMinutes: number): number {
  if (!clockIn || !clockOut) return 0;
  const start = new Date(clockIn).getTime();
  const end = new Date(clockOut).getTime();
  if (Number.isNaN(start) || Number.isNaN(end) || end <= start) return 0;
  const hours = (end - start) / 3_600_000 - breakMinutes / 60;
  return Math.max(0, Math.round(hours * 100) / 100);
}

interface TimesheetPanelProps {
  visitId: string;
  visit: VisitDetail;
}

export function TimesheetPanel({ visitId, visit }: TimesheetPanelProps) {
  const qc = useQueryClient();
  const user = getStoredUser();
  const activeLog = visit.labor_logs.find((l) => l.clock_in && !l.clock_out);
  const canClockIn = ["initiated", "active"].includes(visit.current_state) && !activeLog;
  const canSignoff = visit.current_state === "active" && !!activeLog;

  const [serviceDate, setServiceDate] = useState(todayDateValue());
  const [robotPlatform, setRobotPlatform] = useState<RobotPlatform | "">("");
  const [robotModel, setRobotModel] = useState("");
  const [serialNumber, setSerialNumber] = useState("");
  const [serviceType, setServiceType] = useState<ServiceType | "">("");
  const [clockIn, setClockIn] = useState("");
  const [clockOut, setClockOut] = useState("");
  const [breakMinutes, setBreakMinutes] = useState("0");
  const [findings, setFindings] = useState("");
  const [issuesFound, setIssuesFound] = useState("");
  const [resolution, setResolution] = useState("");
  const [partsUsed, setPartsUsed] = useState("");
  const [travelMiles, setTravelMiles] = useState("");
  const [travelHours, setTravelHours] = useState("");
  const [expenses, setExpenses] = useState("");
  const [followUpRequired, setFollowUpRequired] = useState(false);
  const [attestation, setAttestation] = useState(false);

  useEffect(() => {
    if (activeLog?.clock_in) {
      setClockIn(toDatetimeLocalValue(activeLog.clock_in));
    }
    if (canSignoff && !clockOut) {
      setClockOut(toDatetimeLocalValue(new Date().toISOString()));
    }
  }, [activeLog?.clock_in, canSignoff, clockOut]);

  const billableHours = useMemo(() => {
    if (!clockIn || !clockOut) return 0;
    return computeBillableHours(
      new Date(clockIn).toISOString(),
      new Date(clockOut).toISOString(),
      Number(breakMinutes) || 0,
    );
  }, [clockIn, clockOut, breakMinutes]);

  const clockInMut = useMutation({
    mutationFn: () => api.clockIn(visitId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["visit", visitId] }),
  });

  const signoffMut = useMutation({
    mutationFn: () => {
      const timesheet: TimesheetMetadata = {
        service_date: serviceDate,
        robot_platform: robotPlatform || undefined,
        robot_model: robotModel.trim() || undefined,
        serial_number: serialNumber.trim() || undefined,
        service_type: serviceType || undefined,
        break_minutes: Number(breakMinutes) || 0,
        issues_found: issuesFound.trim() || undefined,
        resolution: resolution.trim() || undefined,
        parts_used: partsUsed.trim() || undefined,
        travel_miles: travelMiles ? Number(travelMiles) : undefined,
        travel_hours: travelHours ? Number(travelHours) : undefined,
        expenses_cents: expenses ? Math.round(Number(expenses) * 100) : undefined,
        follow_up_required: followUpRequired,
        attestation,
      };
      return api.signoff(visitId, {
        clock_in: new Date(clockIn).toISOString(),
        clock_out: new Date(clockOut).toISOString(),
        findings,
        timesheet,
      });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["visit", visitId] }),
  });

  const signoffValid =
    !!robotPlatform &&
    !!serviceType &&
    !!clockIn &&
    !!clockOut &&
    findings.length >= 8 &&
    attestation &&
    billableHours > 0;

  return (
    <div className="panel timesheet-panel">
      <h2>Timesheet</h2>
      <p className="hint">
        Structured sign-off replaces the legacy Google Form. Visit context is pre-filled where possible.
      </p>

      {activeLog && (
        <p className="timesheet-status">
          Clocked in: {new Date(activeLog.clock_in!).toLocaleString()}
        </p>
      )}

      {canClockIn && (
        <button type="button" onClick={() => clockInMut.mutate()} disabled={clockInMut.isPending}>
          Clock In
        </button>
      )}

      {canSignoff && (
        <form
          className="timesheet-form"
          onSubmit={(e) => {
            e.preventDefault();
            if (signoffValid) signoffMut.mutate();
          }}
        >
          <fieldset>
            <legend>Technician &amp; site</legend>
            <div className="form-grid">
              <label>
                Technician email
                <input type="email" value={user.email} readOnly />
              </label>
              <label>
                Date of service
                <input
                  type="date"
                  value={serviceDate}
                  onChange={(e) => setServiceDate(e.target.value)}
                  required
                />
              </label>
              <label>
                Client / POC
                <input type="text" value={visit.metadata_poc.name} readOnly />
              </label>
              <label>
                Service location
                <input type="text" value={visit.location_string} readOnly />
              </label>
            </div>
          </fieldset>

          <fieldset>
            <legend>Robot &amp; service</legend>
            <div className="form-grid">
              <label>
                Robot platform
                <select
                  value={robotPlatform}
                  onChange={(e) => setRobotPlatform(e.target.value as RobotPlatform)}
                  required
                >
                  <option value="">Select platform…</option>
                  {ROBOT_PLATFORMS.map((p) => (
                    <option key={p.value} value={p.value}>
                      {p.label}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Robot model / make
                <input
                  value={robotModel}
                  onChange={(e) => setRobotModel(e.target.value)}
                  placeholder="e.g. Servi Plus, Locus Origin"
                />
              </label>
              <label>
                Serial / asset ID
                <input
                  value={serialNumber}
                  onChange={(e) => setSerialNumber(e.target.value)}
                  placeholder="Robot serial or asset tag"
                />
              </label>
              <label>
                Service type
                <select
                  value={serviceType}
                  onChange={(e) => setServiceType(e.target.value as ServiceType)}
                  required
                >
                  <option value="">Select service type…</option>
                  {SERVICE_TYPES.map((s) => (
                    <option key={s.value} value={s.value}>
                      {s.label}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          </fieldset>

          <fieldset>
            <legend>Time on site</legend>
            <div className="form-grid">
              <label>
                Start time
                <input
                  type="datetime-local"
                  value={clockIn}
                  onChange={(e) => setClockIn(e.target.value)}
                  required
                />
              </label>
              <label>
                End time
                <input
                  type="datetime-local"
                  value={clockOut}
                  onChange={(e) => setClockOut(e.target.value)}
                  required
                />
              </label>
              <label>
                Break / lunch (minutes)
                <input
                  type="number"
                  min={0}
                  max={480}
                  value={breakMinutes}
                  onChange={(e) => setBreakMinutes(e.target.value)}
                />
              </label>
              <label>
                Billable hours
                <input type="text" value={billableHours.toFixed(2)} readOnly />
              </label>
            </div>
          </fieldset>

          <fieldset>
            <legend>Work performed</legend>
            <label>
              Description of work performed
              <textarea
                value={findings}
                onChange={(e) => setFindings(e.target.value)}
                rows={4}
                required
                minLength={8}
                placeholder="Summarize tasks completed on site"
              />
            </label>
            <label>
              Issues found
              <textarea
                value={issuesFound}
                onChange={(e) => setIssuesFound(e.target.value)}
                rows={3}
                placeholder="Errors, faults, or observations"
              />
            </label>
            <label>
              Resolution / outcome
              <textarea
                value={resolution}
                onChange={(e) => setResolution(e.target.value)}
                rows={3}
                placeholder="What was fixed, replaced, or escalated"
              />
            </label>
            <label>
              Parts / materials used
              <textarea
                value={partsUsed}
                onChange={(e) => setPartsUsed(e.target.value)}
                rows={2}
                placeholder="Part numbers, quantities, consumables"
              />
            </label>
          </fieldset>

          <fieldset>
            <legend>Travel &amp; expenses</legend>
            <div className="form-grid">
              <label>
                Travel miles
                <input
                  type="number"
                  min={0}
                  step={0.1}
                  value={travelMiles}
                  onChange={(e) => setTravelMiles(e.target.value)}
                  placeholder="Round-trip or one-way"
                />
              </label>
              <label>
                Travel time (hours)
                <input
                  type="number"
                  min={0}
                  step={0.25}
                  value={travelHours}
                  onChange={(e) => setTravelHours(e.target.value)}
                />
              </label>
              <label>
                Out-of-pocket expenses ($)
                <input
                  type="number"
                  min={0}
                  step={0.01}
                  value={expenses}
                  onChange={(e) => setExpenses(e.target.value)}
                />
              </label>
            </div>
          </fieldset>

          <fieldset>
            <legend>Sign-off</legend>
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={followUpRequired}
                onChange={(e) => setFollowUpRequired(e.target.checked)}
              />
              Follow-up visit required
            </label>
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={attestation}
                onChange={(e) => setAttestation(e.target.checked)}
                required
              />
              I certify that this timesheet is accurate and complete
            </label>
          </fieldset>

          <button type="submit" className="primary" disabled={!signoffValid || signoffMut.isPending}>
            {signoffMut.isPending ? "Submitting…" : "Submit Timesheet & Sign Off"}
          </button>
        </form>
      )}

      {(clockInMut.error || signoffMut.error) && (
        <p className="error">{((clockInMut.error ?? signoffMut.error) as Error).message}</p>
      )}
    </div>
  );
}
