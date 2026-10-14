/** Maintenance actions (build step 10b). */
import type { MessageValues } from "./alertTypes.ts";

export type ActionStatus = "requested" | "assigned" | "in_progress" | "waiting" | "done" | "verified" | "cancelled";
export const ACTION_STATUSES: ActionStatus[] = ["requested", "assigned", "in_progress", "waiting", "done", "verified", "cancelled"];
/** The main path, for the status bar. */
export const STATUS_PATH: ActionStatus[] = ["requested", "assigned", "in_progress", "done", "verified"];
export type Priority = "low" | "medium" | "high" | "urgent";
export const PRIORITIES: Priority[] = ["low", "medium", "high", "urgent"];
export type ActionType = "corrective" | "inspection" | "improvement";
export const ACTION_TYPES: ActionType[] = ["corrective", "inspection", "improvement"];

export interface Person {
  id: number;
  email: string;
}

export interface AllowedStep {
  to: ActionStatus;
  event: string;
  note_required: boolean;
}

export interface MaintenanceAction {
  id: number;
  factory: number;
  line: number;
  line_name: string;
  machine: number;
  machine_name: string;
  factory_timezone: string;
  title: string;
  problem: string;
  action_type: ActionType;
  priority: Priority;
  status: ActionStatus;
  reporter: Person;
  assignee: number | null;
  assignee_detail: Person | null;
  due_date: string | null;
  is_overdue: boolean;
  started_at: string | null;
  completed_at: string | null;
  fixed_at: string | null;
  verified_by: Person | null;
  verified_at: string | null;
  verification_result: "" | "effective" | "not_effective";
  verification_note: string;
  effectiveness_window_days: number;
  min_after_run_hours: number;
  created_at: string;
  updated_at: string;
  allowed_steps: AllowedStep[];
  link_count: number;
}

export type LinkInput =
  | { kind: "downtime_event" | "incident" | "alert" | "inspection_result"; id: number }
  | { kind: "signature"; machine: number; reason?: number | null; alarm_code?: string };

export interface ActionInput {
  machine: number;
  title: string;
  problem: string;
  action_type: ActionType;
  links?: LinkInput[];
}

export interface Prefill {
  machine: number;
  machine_name: string;
  line: number;
  line_name: string;
  title: string;
  problem: string;
  links: LinkInput[];
}

export type PrefillSource =
  | { source: "incident" | "alert" | "inspection_result" | "machine"; id: number }
  | { source: "recurring"; machine: number; reason?: number; alarm?: string; start: string; end: string };

export interface ActionLink {
  id: number;
  kind: LinkInput["kind"];
  created_at: string;
  target: Record<string, unknown> & {
    id?: number;
    machine?: string | { id: number; name: string };
    started_at?: string;
    timestamp?: string;
    opened_at?: string;
  };
}

export interface Part {
  name: string;
  quantity: number;
}

export interface WorkEntry {
  id: number;
  kind: "comment" | "diagnosis" | "repair";
  text: string;
  time_spent_minutes: number;
  parts: Part[];
  author: Person;
  created_at: string;
}

export interface StatusChange {
  id: number;
  from_status: ActionStatus;
  to_status: ActionStatus;
  event: string;
  note: string;
  changed_by: Person;
  changed_at: string;
}

export interface Diagnosis {
  id: number;
  reason: { id: number; code: string; name: string };
  text: string;
  applied_to_stops: boolean;
  replace_other_reasons: boolean;
  applied_count: number;
  skipped_count: number;
  created_by: Person;
  created_at: string;
}

export interface DiagnosisPreview {
  linked_stops: number;
  unclassified: number;
  same_reason: number;
  same_category: number;
  other_reasons: { code: string; name: string; count: number }[];
  would_apply: number;
  would_apply_with_replace: number;
}

export interface EffectWindow {
  start: string;
  end: string;
  occurrences: number;
  downtime_seconds: number;
  run_hours: number;
  occurrences_per_10h: number | null;
  downtime_minutes_per_10h: number | null;
}

export type EffectStatus = "improved" | "no_change" | "worse" | "not_enough_data" | "no_signature" | "not_fixed";

export interface Effectiveness {
  status: EffectStatus;
  reason?: "after_run_time" | "before_run_time" | "few_occurrences_before";
  missing_run_hours?: number;
  fixed_at: string | null;
  window_days: number;
  min_after_run_hours: number;
  min_before_occurrences: number;
  signature: { machine: { id: number; name: string }; reason: { code: string; name: string } | null; alarm_code: string | null } | null;
  before?: EffectWindow;
  after?: EffectWindow | null;
  message_key?: string;
  message_values?: MessageValues;
}
