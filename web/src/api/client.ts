import type { TimesheetMetadata } from "../constants/timesheet";

const API_BASE = import.meta.env.VITE_API_BASE ?? "";

export type UserRole = "technician" | "finance_manager" | "admin";

const STORAGE_KEY = "rr_ops_user";

export function getStoredUser(): { email: string; role: UserRole } {
  const raw = localStorage.getItem(STORAGE_KEY);
  if (raw) {
    try {
      return JSON.parse(raw);
    } catch {
      /* fall through */
    }
  }
  return { email: "field.tech@roboreliance.internal", role: "technician" };
}

export function setStoredUser(email: string, role: UserRole) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify({ email, role }));
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const user = getStoredUser();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    "X-User-Email": user.email,
    "X-User-Role": user.role,
    ...(options.headers as Record<string, string> | undefined),
  };
  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? res.statusText);
  }
  return res.json() as Promise<T>;
}

export const api = {
  createVisit: (body: {
    location_string: string;
    metadata_poc: { name: string; phone: string; email: string };
    slack_channel_id?: string;
  }) =>
    request<{ visit_id: string; visit_state: string }>("/api/v1/visits", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  listVisits: (params?: { state?: string; include_completed?: boolean }) => {
    const parts: string[] = [];
    if (params?.state) parts.push(`state=${encodeURIComponent(params.state)}`);
    if (params?.include_completed) parts.push("include_completed=true");
    const q = parts.length ? `?${parts.join("&")}` : "";
    return request<{ visits: Visit[] }>(`/api/v1/visits${q}`);
  },

  getVisit: (id: string) => request<VisitDetail>(`/api/v1/visits/${id}`),

  clockIn: (id: string) =>
    request(`/api/v1/visits/${id}/clock-in`, { method: "POST", body: "{}" }),

  signoff: (
    id: string,
    body: {
      clock_in: string;
      clock_out: string;
      findings: string;
      timesheet?: TimesheetMetadata;
    },
  ) => request(`/api/v1/visits/${id}/signoff`, { method: "POST", body: JSON.stringify(body) }),

  financeLedgers: (params?: { approval_state?: string }) => {
    const q = params?.approval_state
      ? `?approval_state=${encodeURIComponent(params.approval_state)}`
      : "";
    return request<{ ledgers: FinanceLedger[] }>(`/api/v1/finance/ledgers${q}`);
  },

  financePending: () => request<{ pending: FinanceLedger[] }>("/api/v1/finance/pending"),

  financeLedger: (id: string) => request<FinanceLedgerDetail>(`/api/v1/finance/ledger/${id}`),

  financeApprove: (body: {
    approval_token: string;
    action: "approve" | "reject";
    rejection_reason?: string;
  }) =>
    request("/api/v1/finance/approve", { method: "POST", body: JSON.stringify(body) }),

  webChat: (body: { message: string; visit_id?: string; session_id?: string }) =>
    request<{ reply: string; citations: string[] }>("/api/v1/web-chat/message", {
      method: "POST",
      body: JSON.stringify(body),
    }),
};

export interface Visit {
  visit_id: string;
  slack_channel_id: string | null;
  google_space_id: string;
  location_string: string;
  metadata_poc: { name: string; phone: string; email: string };
  current_state: string;
  created_at: string;
  technician_identity?: string;
  pay_status?: string | null;
  payout_cents?: number | null;
}

export interface LaborLog {
  log_id: string;
  technician_identity: string;
  clock_in: string | null;
  clock_out: string | null;
  extracted_findings: string | null;
  timesheet_metadata?: TimesheetMetadata | null;
  is_verified: boolean;
}

export interface VisitDetail extends Visit {
  labor_logs: LaborLog[];
  financial_ledgers: Array<{
    ledger_id: string;
    approval_state: string;
    calculated_hours: number;
    invoice_cents: number;
    payout_cents: number;
  }>;
}

export interface FinanceLedger {
  ledger_id: string;
  visit_id: string;
  calculated_hours: number;
  invoice_cents: number;
  payout_cents: number;
  approval_state: string;
  location_string: string;
  qbo_invoice_reference?: string;
  technician_identity?: string;
  extracted_findings?: string;
  created_at?: string;
  updated_at?: string;
}

export interface FinanceLedgerDetail extends FinanceLedger {
  visit_state: string;
  metadata_poc: { name: string; phone: string; email: string };
  clock_in?: string;
  clock_out?: string;
  timesheet_metadata?: TimesheetMetadata | null;
  approval_token?: string;
  audit_trail?: Array<{ execution_context: string; timestamp: string }>;
}
