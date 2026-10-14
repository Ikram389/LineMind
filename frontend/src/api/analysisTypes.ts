/** Types for downtime analysis and classification (build step 8). */
import type {
  Classification,
  DowntimeCategory,
  DowntimeEvent,
  MachineSummary,
} from "./types.ts";

export type AnalysisView = "line" | "machine";
export type ParetoGroupBy = "reason" | "machine" | "category" | "alarm_code";
export type RoleInIncident = "first_observed_stop" | "secondary_breakdown" | "consequence" | null;

export interface EstimatedUnits {
  units: number;
  is_estimate: true;
  basis: string;
}

export interface ParetoGroup {
  key: string;
  label: string;
  total_seconds: number;
  total_micros: number;
  occurrences: number;
  estimated_lost_units: EstimatedUnits;
  share: number;
  cumulative_share: number;
}

export interface ParetoResponse {
  view: AnalysisView;
  view_note: string;
  group_by: ParetoGroupBy;
  total_seconds: number;
  total_occurrences: number;
  estimated_lost_units: EstimatedUnits;
  groups: ParetoGroup[];
}

export interface ReasonSummary {
  id: number;
  code: string;
  name: string;
  category: string;
}

export interface SummaryResponse {
  view: AnalysisView;
  view_note: string;
  total_seconds: number;
  stops: number;
  unclassified: number;
  secondary_breakdowns: number;
  longest: {
    machine: MachineSummary;
    started_at: string;
    duration_seconds: number;
    category: DowntimeCategory;
    reason: ReasonSummary | null;
    incident: number | null;
  } | null;
  estimated_lost_units: EstimatedUnits;
}

export interface RecurringItem {
  machine: MachineSummary;
  reason: ReasonSummary | null;
  alarm_code: string | null;
  count: number;
  threshold: number;
  total_seconds: number;
  last_occurrence: string;
}

export interface RecurringResponse {
  threshold: number | null;
  items: RecurringItem[];
}

export type ReasonCategory =
  | "mechanical"
  | "electrical"
  | "material"
  | "quality"
  | "organizational"
  | "planned";

export const REASON_CATEGORIES: ReasonCategory[] = [
  "mechanical",
  "electrical",
  "material",
  "quality",
  "organizational",
  "planned",
];

export interface Reason {
  id: number;
  factory: number;
  code: string;
  name: string;
  category: ReasonCategory;
  is_active: boolean;
  is_changeover: boolean;
  in_use: boolean;
}

export interface AnalysedDowntimeEvent extends DowntimeEvent {
  role_in_incident: RoleInIncident;
  clipped_duration_seconds: number | null;
}

export interface IncidentMember extends AnalysedDowntimeEvent {
  delay_seconds: number;
  classifications: Classification[];
}

export interface IncidentDetail {
  id: number;
  line: { id: number; name: string };
  started_at: string;
  ended_at: string | null;
  duration_seconds: number;
  is_ongoing: boolean;
  origin: "machine_stop" | "unknown";
  events: IncidentMember[];
}

export interface ShiftOccurrence {
  shift_id: number;
  name: string;
  label: string;
  local_date: string;
  start: string;
  end: string;
}
