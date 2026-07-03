export const ROBOT_PLATFORMS = [
  { value: "food_service", label: "Food Service Robotics" },
  { value: "warehouse_logistics", label: "Warehouse / Logistics" },
  { value: "agriculture", label: "Agriculture" },
  { value: "healthcare", label: "Healthcare" },
  { value: "humanoid", label: "Humanoid" },
  { value: "other", label: "Other" },
] as const;

export const SERVICE_TYPES = [
  { value: "installation", label: "Installation" },
  { value: "preventive_maintenance", label: "Preventive Maintenance" },
  { value: "repair", label: "Repair" },
  { value: "emergency", label: "Emergency Service" },
  { value: "training", label: "Training / Commissioning" },
  { value: "other", label: "Other" },
] as const;

export type RobotPlatform = (typeof ROBOT_PLATFORMS)[number]["value"];
export type ServiceType = (typeof SERVICE_TYPES)[number]["value"];

export interface TimesheetMetadata {
  service_date?: string;
  robot_platform?: RobotPlatform;
  robot_model?: string;
  serial_number?: string;
  service_type?: ServiceType;
  break_minutes?: number;
  issues_found?: string;
  resolution?: string;
  parts_used?: string;
  travel_miles?: number;
  travel_hours?: number;
  expenses_cents?: number;
  follow_up_required?: boolean;
  attestation?: boolean;
}

export function platformLabel(value?: string) {
  return ROBOT_PLATFORMS.find((p) => p.value === value)?.label ?? value ?? "—";
}

export function serviceTypeLabel(value?: string) {
  return SERVICE_TYPES.find((s) => s.value === value)?.label ?? value ?? "—";
}

export function formatCents(cents?: number | null) {
  if (cents == null) return "—";
  return `$${(cents / 100).toFixed(2)}`;
}
