/** Quality records, metrics and configuration (build step 9). */

export type Severity = "minor" | "major" | "critical";
export const SEVERITIES: Severity[] = ["minor", "major", "critical"];
export type Verdict = "confirmed" | "false_reject" | "reclassified";
export type QualityGroupBy = "defect_type" | "station" | "machine" | "product";
export type TrendGroupBy = "hour" | "shift" | "day";

export interface DefectType {
  id: number;
  code: string;
  name: string;
  description: string;
  severity: Severity;
  is_active: boolean;
  in_use: boolean;
}

export interface DefectTypeSummary {
  id: number;
  code: string;
  name: string;
  severity: Severity;
}

export interface InspectionStation {
  id: number;
  line: number;
  machine: number;
  machine_name: string;
  name: string;
  defect_types: number[];
  source: "simulator" | "vision";
  is_active: boolean;
  in_use: boolean;
}

export interface QualityReview {
  id: number;
  verdict: Verdict;
  corrected_defect_type: DefectTypeSummary | null;
  comment: string;
  reviewed_by: string;
  reviewed_at: string;
}

export interface DefectIncidentContext {
  id: number;
  ended_at: string;
  seconds_after: number;
  first_observed_stop: { machine: string; alarm_code: string | null } | null;
  /** e.g. "Occurred 2 min after incident #14 ended (first observed stop: Labeler, E-204)" */
  text: string;
}

export interface DefectContext {
  product: { id: number; sku: string; name: string } | null;
  order_id: number | null;
  machine_state: string;
  machine_state_since: string | null;
  last_alarm_code: string | null;
  last_alarm_at: string | null;
  incident: DefectIncidentContext | null;
}

export interface InspectionResult {
  id: number;
  event_id: string;
  line: number;
  machine: { id: number; external_id: string; name: string };
  station: { id: number; name: string } | null;
  timestamp: string;
  reported_code: string;
  defect_type: DefectTypeSummary | null;
  effective_defect_type: DefectTypeSummary | null;
  /** false once a review says "false reject" */
  is_defect: boolean;
  confidence: number | null;
  source: string;
  outcome: "rejected";
  warnings: string[];
  review: QualityReview | null;
  context: DefectContext | null;
}

export interface StationInspection {
  station: {
    id: number;
    name: string;
    machine: { id: number; external_id: string; name: string };
    is_active: boolean;
  };
  inspected: number;
  defects: number;
  defect_rate: number | null;
}

export interface QualitySummary {
  inspected_by_station: StationInspection[];
  defects_without_station: number;
  line_total_count: number;
  line_counts: {
    counting_machine_output: number;
    counting_machine_rejected: number;
    upstream_rejected: number;
  };
  defects: number;
  defect_rate: number | null;
  defects_by_severity: Record<Severity | "unknown", number>;
  false_rejects: number;
  unreviewed: number;
  results_with_warnings: number;
  warnings: string[];
}

export interface QualityParetoGroup {
  key: string; // e.g. "defect_type:3", "station:none"
  id: number | null;
  label: string;
  code?: string;
  severity?: Severity;
  count: number;
  share: number | null;
  cumulative_share: number | null;
}

export interface QualityPareto {
  group_by: QualityGroupBy;
  total: number;
  false_rejects_excluded: number;
  groups: QualityParetoGroup[];
}

export interface TrendBucket {
  start: string;
  end: string;
  label: string;
  defects: number;
  total_count: number;
  defect_rate: number | null;
}

export interface QualityTrend {
  group_by: TrendGroupBy;
  buckets: TrendBucket[];
  total: { defects: number; total_count: number; defect_rate: number | null };
}

/** The current shift's quality, from the summary or a quality_updated message. */
export interface ShiftQuality {
  shift: { label: string; start: string; end: string } | null;
  defects: number;
  defect_rate: number | null;
  unreviewed: number;
  total_count: number;
}
