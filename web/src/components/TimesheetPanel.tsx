import { useEffect, useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, getStoredUser, VisitDetail } from "../api/client";
import {
  COMPLETION_STATUSES,
  computeBillableHours,
  FOLLOW_UP_STATUSES,
  formatBillableHours,
  WORK_CATEGORIES,
  type CompletionStatus,
  type FollowUpStatus,
  type MediaFileRef,
  type TimesheetMetadata,
  type WorkCategory,
} from "../constants/timesheet";

const MAX_MEDIA_FILES = 10;
const MAX_MEDIA_BYTES = 1_073_741_824;

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
  const [workOrderNumber, setWorkOrderNumber] = useState("");
  const [invoiceNumber, setInvoiceNumber] = useState("");
  const [clockIn, setClockIn] = useState("");
  const [clockOut, setClockOut] = useState("");
  const [findings, setFindings] = useState("");
  const [mediaFiles, setMediaFiles] = useState<MediaFileRef[]>([]);
  const [mediaError, setMediaError] = useState("");
  const [completionStatus, setCompletionStatus] = useState<CompletionStatus | "">("");
  const [followUpStatus, setFollowUpStatus] = useState<FollowUpStatus | "">("");
  const [difficultyRating, setDifficultyRating] = useState<number | null>(null);
  const [workCategories, setWorkCategories] = useState<WorkCategory[]>([]);
  const [toolsEquipment, setToolsEquipment] = useState("");
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
    return computeBillableHours(new Date(clockIn).toISOString(), new Date(clockOut).toISOString());
  }, [clockIn, clockOut]);

  const clockInMut = useMutation({
    mutationFn: () => api.clockIn(visitId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["visit", visitId] }),
  });

  const signoffMut = useMutation({
    mutationFn: () => {
      const timesheet: TimesheetMetadata = {
        service_date: serviceDate,
        customer_site_name: visit.location_string,
        work_order_number: workOrderNumber.trim() || undefined,
        invoice_number: invoiceNumber.trim() || undefined,
        completion_status: completionStatus || undefined,
        follow_up_status: followUpStatus || undefined,
        difficulty_rating: difficultyRating ?? undefined,
        work_categories: workCategories,
        tools_equipment: toolsEquipment.trim() || undefined,
        media_files: mediaFiles.length ? mediaFiles : undefined,
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

  function toggleWorkCategory(category: WorkCategory) {
    setWorkCategories((prev) =>
      prev.includes(category) ? prev.filter((c) => c !== category) : [...prev, category],
    );
  }

  function handleMediaChange(files: FileList | null) {
    setMediaError("");
    if (!files?.length) {
      setMediaFiles([]);
      return;
    }
    if (files.length > MAX_MEDIA_FILES) {
      setMediaError(`Upload up to ${MAX_MEDIA_FILES} files.`);
      return;
    }
    const next: MediaFileRef[] = [];
    for (const file of Array.from(files)) {
      if (file.size > MAX_MEDIA_BYTES) {
        setMediaError(`${file.name} exceeds the 1 GB limit.`);
        return;
      }
      next.push({ name: file.name, size_bytes: file.size });
    }
    setMediaFiles(next);
  }

  const signoffValid =
    !!serviceDate &&
    !!clockIn &&
    !!clockOut &&
    findings.length >= 8 &&
    !!completionStatus &&
    !!followUpStatus &&
    difficultyRating != null &&
    workCategories.length > 0 &&
    attestation &&
    billableHours > 0 &&
    !mediaError;

  return (
    <div className="panel timesheet-panel">
      <h2>Technician Site Visit Timesheet</h2>
      <p className="hint">
        Log arrival and departure times for this site visit. Total hours are calculated and rounded
        up to the nearest 15 minutes.
      </p>

      {activeLog && (
        <p className="timesheet-status">
          Clocked in: {new Date(activeLog.clock_in!).toLocaleString()}
        </p>
      )}

      {canClockIn && (
        <button type="button" onClick={() => clockInMut.mutate()} disabled={clockInMut.isPending}>
          Clock In (Arrival)
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
                Email
                <input type="email" value={user.email} readOnly />
              </label>
              <label>
                Customer / site name
                <input type="text" value={visit.location_string} readOnly />
              </label>
              <label>
                Client work order or job number
                <input
                  value={workOrderNumber}
                  onChange={(e) => setWorkOrderNumber(e.target.value)}
                  placeholder="If applicable"
                />
              </label>
              <label>
                Your invoice number
                <input
                  value={invoiceNumber}
                  onChange={(e) => setInvoiceNumber(e.target.value)}
                  placeholder="If applicable"
                />
              </label>
              <label>
                Date of site visit
                <input
                  type="date"
                  value={serviceDate}
                  onChange={(e) => setServiceDate(e.target.value)}
                  required
                />
              </label>
            </div>
          </fieldset>

          <fieldset>
            <legend>Time on site</legend>
            <div className="form-grid">
              <label>
                Time of arrival (on site)
                <input
                  type="datetime-local"
                  value={clockIn}
                  onChange={(e) => setClockIn(e.target.value)}
                  required
                />
              </label>
              <label>
                Time of departure (from site)
                <input
                  type="datetime-local"
                  value={clockOut}
                  onChange={(e) => setClockOut(e.target.value)}
                  required
                />
              </label>
              <label>
                Billable time (rounded up to 15 min)
                <input type="text" value={formatBillableHours(billableHours)} readOnly />
              </label>
            </div>
          </fieldset>

          <fieldset>
            <legend>Work performed</legend>
            <label>
              Detailed description of work performed
              <textarea
                value={findings}
                onChange={(e) => setFindings(e.target.value)}
                rows={5}
                required
                minLength={8}
                placeholder="Describe the work completed on site"
              />
            </label>
          </fieldset>

          <fieldset>
            <legend>Photos / videos</legend>
            <p className="field-help">
              Before/after repair, spoofing video, etc. Upload up to 10 supported files (max 1 GB
              each). Large files or spoofing videos can also be sent via the visit Google Chat or
              Slack channel.
            </p>
            <input
              type="file"
              multiple
              accept="image/*,video/*"
              onChange={(e) => handleMediaChange(e.target.files)}
            />
            {mediaFiles.length > 0 && (
              <ul className="media-file-list">
                {mediaFiles.map((file) => (
                  <li key={file.name}>
                    {file.name} ({(file.size_bytes / 1024 / 1024).toFixed(1)} MB)
                  </li>
                ))}
              </ul>
            )}
            {mediaError && <p className="error">{mediaError}</p>}
          </fieldset>

          <fieldset>
            <legend>Visit outcome</legend>
            <div className="field-group">
              <span className="field-label">Was the work completed satisfactorily?</span>
              <div className="radio-group">
                {COMPLETION_STATUSES.map((option) => (
                  <label key={option.value} className="radio-label">
                    <input
                      type="radio"
                      name="completion_status"
                      value={option.value}
                      checked={completionStatus === option.value}
                      onChange={() => setCompletionStatus(option.value)}
                      required
                    />
                    {option.label}
                  </label>
                ))}
              </div>
            </div>

            <div className="field-group">
              <span className="field-label">Did this visit require any follow-up or next steps?</span>
              <div className="radio-group">
                {FOLLOW_UP_STATUSES.map((option) => (
                  <label key={option.value} className="radio-label">
                    <input
                      type="radio"
                      name="follow_up_status"
                      value={option.value}
                      checked={followUpStatus === option.value}
                      onChange={() => setFollowUpStatus(option.value)}
                      required
                    />
                    {option.label}
                  </label>
                ))}
              </div>
            </div>
          </fieldset>

          <fieldset>
            <legend>Analytics</legend>
            <div className="field-group">
              <span className="field-label">
                Rate the level of difficulty for the work performed on site
              </span>
              <div className="difficulty-scale">
                <span className="scale-end">Very Low</span>
                {[1, 2, 3, 4, 5].map((value) => (
                  <label key={value} className="scale-option">
                    <input
                      type="radio"
                      name="difficulty_rating"
                      value={value}
                      checked={difficultyRating === value}
                      onChange={() => setDifficultyRating(value)}
                      required
                    />
                    {value}
                  </label>
                ))}
                <span className="scale-end">Very High</span>
              </div>
            </div>

            <div className="field-group">
              <span className="field-label">
                Which categories best describe the type of work performed? (Select all that apply)
              </span>
              <div className="checkbox-group">
                {WORK_CATEGORIES.map((category) => (
                  <label key={category.value} className="checkbox-label">
                    <input
                      type="checkbox"
                      checked={workCategories.includes(category.value)}
                      onChange={() => toggleWorkCategory(category.value)}
                    />
                    {category.label}
                  </label>
                ))}
              </div>
            </div>

            <label>
              Which tools or specialized equipment were essential for completing the work?
              <textarea
                value={toolsEquipment}
                onChange={(e) => setToolsEquipment(e.target.value)}
                rows={3}
                placeholder="List tools, test equipment, lifts, etc."
              />
            </label>
          </fieldset>

          <fieldset>
            <legend>Confirmation</legend>
            <label className="checkbox-label attestation-label">
              <input
                type="checkbox"
                checked={attestation}
                onChange={(e) => setAttestation(e.target.checked)}
                required
              />
              <span>
                I confirm that the recorded date, arrival time, and departure time are accurate and
                ready for submission/customer billing. I understand that the total time will be
                calculated and rounded up to the nearest 15 minutes.
              </span>
            </label>
          </fieldset>

          <button type="submit" className="primary" disabled={!signoffValid || signoffMut.isPending}>
            {signoffMut.isPending ? "Submitting…" : "Submit Timesheet"}
          </button>
        </form>
      )}

      {(clockInMut.error || signoffMut.error) && (
        <p className="error">{((clockInMut.error ?? signoffMut.error) as Error).message}</p>
      )}
    </div>
  );
}
