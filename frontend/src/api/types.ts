/** Types matching the LineMind backend API (/api/v1/). Dates are ISO 8601 strings in UTC. */
import type { AlertSeverity, AlertStatus, MessageValues, RuleType } from "./alertTypes.ts";
import type { ShiftQuality } from "./qualityTypes.ts";

export type MachineState =
  | "running"
  | "stopped"
  | "blocked"
  | "starved"
  | "planned_stop"
  | "unknown";

export type Role =
  | "platform_admin"
  | "factory_manager"
  | "production_supervisor"
  | "machine_operator"
  | "maintenance_technician"
  | "quality_inspector"
  | "analyst";

export interface Tokens {
  access: string;
  refresh: string;
}

export interface FactorySummary {
  id: number;
  name: string;
  timezone: string;
}

export interface Me {
  id: number;
  email: string;
  full_name: string;
  organization: { id: number; name: string } | null;
  role: Role | null;
  all_factories: boolean;
  factories: FactorySummary[];
}

export interface Factory {
  id: number;
  organization: number;
  name: string;
  timezone: string;
  stale_after_seconds: number;
}

export interface Line {
  id: number;
  factory: number;
  name: string;
  counting_machine: number | null;
}

export interface MachineSummary {
  id: number;
  external_id: string;
  name: string;
}

export interface MachineStatus extends MachineSummary {
  position: number;
  state: MachineState;
  reported_state: MachineState | null;
  state_since: string | null;
  alarm_code: string | null;
  last_alarm_code: string | null;
  last_alarm_at: string | null;
  is_stale: boolean;
  last_seen: string | null;
  shift_count: number | null;
  shift_rejected: number | null;
  last_count: { count: number; rejected: number | null; timestamp: string } | null;
}

export type DowntimeCategory = "breakdown" | "blocked" | "starved" | "planned" | "no_data";

export interface AffectedMachine extends MachineSummary {
  category: DowntimeCategory;
  started_at: string;
  ended_at: string | null;
  is_first_stop: boolean;
}

export interface Incident {
  incident_id: number;
  started_at: string;
  ended_at: string | null;
  origin: "machine_stop" | "unknown";
  first_observed_stop: { machines: MachineSummary[]; alarm_code: string | null };
  affected_machines: AffectedMachine[];
}

export interface LineStatus {
  line: { id: number; name: string };
  factory_timezone: string;
  stale_after_seconds: number;
  generated_at: string;
  current_shift_start: string | null;
  machines: MachineStatus[];
  open_incident: Incident | null;
}

export interface CurrentShift {
  shift_id: number;
  name: string;
  label: string;
  local_date: string;
  start: string;
  end: string;
  breaks: { start: string; end: string }[];
  factory_timezone: string;
}

export interface Ratio {
  ratio: number | null;
  percent: number | null;
  null_reason?: string | null;
}

export interface OeeWarning {
  code: string;
  message: string;
}

export interface OeeResult {
  availability: Ratio;
  performance: Ratio;
  quality: Ratio;
  oee: Ratio;
  data_coverage: Ratio;
  null_reason: string | null;
  warnings: OeeWarning[];
  inputs: Record<string, unknown>;
}

export interface OeeBucket extends OeeResult {
  label: string;
  start: string;
  end: string;
}

export interface OeeResponse {
  line: { id: number; name: string };
  counting_machine: string;
  factory_timezone: string;
  total: OeeResult;
  group_by?: "hour" | "day" | "shift";
  buckets?: OeeBucket[];
}

export interface Classification {
  id: number;
  reason: { id: number; code: string; name: string; category: string };
  comment: string;
  source: string;
  created_by: string | null;
  created_at: string;
}

export interface DowntimeEvent {
  id: number;
  machine: MachineSummary & { position: number };
  line: number;
  category: DowntimeCategory;
  state: string;
  started_at: string;
  ended_at: string | null;
  duration_seconds: number;
  is_ongoing: boolean;
  alarm_code: string | null;
  is_first_stop: boolean;
  incident: number | null;
  classification: Classification | null;
}

export interface Paginated<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

// --- Live messages (WebSocket /ws/lines/<id>/) ---------------------------------------

interface Envelope<Type extends string, Data> {
  type: Type;
  line_id: number;
  sent_at: string;
  data: Data;
}

export type MachineStateChanged = Envelope<
  "machine_state_changed",
  Pick<
    MachineStatus,
    | "state"
    | "reported_state"
    | "state_since"
    | "alarm_code"
    | "last_alarm_code"
    | "last_alarm_at"
    | "is_stale"
    | "last_seen"
  > & { machine_id: number; external_id: string }
>;

export type CountUpdated = Envelope<
  "count_updated",
  {
    machine_id: number;
    external_id: string;
    count: number | null;
    rejected: number | null;
    timestamp: string | null;
    shift_count: number | null;
    shift_rejected: number | null;
    last_seen: string | null;
  }
>;

export type IncidentChanged = Envelope<"incident_opened" | "incident_updated", Incident>;

export type IncidentClosed = Envelope<
  "incident_closed",
  { incident_id: number; started_at: string; ended_at: string | null; duration_seconds: number | null }
>;

export type QualityUpdated = Envelope<"quality_updated", ShiftQuality>;

/** What alert messages carry (a summary of the alert). */
export interface AlertSummary {
  alert_id: number;
  rule_type: RuleType;
  severity: AlertSeverity;
  status: AlertStatus;
  line_id: number | null;
  machine_id: number | null;
  subject_type: string;
  subject_id: number | null;
  opened_at: string;
  condition_since: string;
  message_key: string;
  message_values: MessageValues;
  acknowledged_at: string | null;
  resolved_at: string | null;
  resolution: string;
}

export type AlertChanged = Envelope<"alert_opened" | "alert_updated" | "alert_resolved", AlertSummary>;

/** Sent to the user's own socket (/ws/me/). */
export type NotificationsChanged = Envelope<"notifications_changed", { unread_count: number }>;

export type LiveMessage =
  | MachineStateChanged
  | CountUpdated
  | IncidentChanged
  | IncidentClosed
  | QualityUpdated
  | AlertChanged;
