export const COMPLETION_STATUSES = [
  { value: "yes_fully_completed", label: "Yes, fully completed" },
  { value: "no_still_pending", label: "No, work is still pending" },
  { value: "na_diagnosis_only", label: "N/A (e.g., diagnosis only)" },
] as const;

export const FOLLOW_UP_STATUSES = [
  { value: "no_complete", label: "No, the job is complete." },
  { value: "yes_return_visit", label: "Yes, a return visit is required." },
  { value: "yes_remote_followup", label: "Yes, remote follow-up is needed." },
] as const;

export const WORK_CATEGORIES = [
  { value: "installation_setup", label: "Installation/Setup" },
  { value: "troubleshooting_diagnosis", label: "Troubleshooting/Diagnosis" },
  { value: "repair_maintenance", label: "Repair/Maintenance" },
  { value: "consultation_training", label: "Consultation/Training" },
  { value: "preventative_check", label: "Preventative Check" },
  { value: "software_update_configuration", label: "Software Update/Configuration" },
] as const;

export type CompletionStatus = (typeof COMPLETION_STATUSES)[number]["value"];
export type FollowUpStatus = (typeof FOLLOW_UP_STATUSES)[number]["value"];
export type WorkCategory = (typeof WORK_CATEGORIES)[number]["value"];

export interface MediaFileRef {
  name: string;
  size_bytes: number;
}

export interface TimesheetMetadata {
  service_date?: string;
  customer_site_name?: string;
  work_order_number?: string;
  invoice_number?: string;
  completion_status?: CompletionStatus;
  follow_up_status?: FollowUpStatus;
  difficulty_rating?: number;
  work_categories?: WorkCategory[];
  tools_equipment?: string;
  media_files?: MediaFileRef[];
  attestation?: boolean;
}

export function completionStatusLabel(value?: string) {
  return COMPLETION_STATUSES.find((s) => s.value === value)?.label ?? value ?? "—";
}

export function followUpStatusLabel(value?: string) {
  return FOLLOW_UP_STATUSES.find((s) => s.value === value)?.label ?? value ?? "—";
}

export function workCategoryLabel(value: string) {
  return WORK_CATEGORIES.find((c) => c.value === value)?.label ?? value;
}

/** Billable hours rounded up to the nearest 15 minutes (matches legacy Google Form). */
export function computeBillableHours(clockIn: string, clockOut: string): number {
  const start = new Date(clockIn).getTime();
  const end = new Date(clockOut).getTime();
  if (Number.isNaN(start) || Number.isNaN(end) || end <= start) return 0;
  const minutes = (end - start) / 60_000;
  const roundedMinutes = Math.ceil(minutes / 15) * 15;
  return Math.round((roundedMinutes / 60) * 100) / 100;
}

export function formatBillableHours(hours: number): string {
  const wholeHours = Math.floor(hours);
  const mins = Math.round((hours - wholeHours) * 60);
  if (mins === 0) return `${wholeHours} hr`;
  return `${wholeHours} hr ${mins} min`;
}
