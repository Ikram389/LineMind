import type {
  DefectType,
  InspectionResult,
  QualityPareto,
  QualitySummary,
  QualityTrend,
} from "../api/qualityTypes.ts";

export function makeDefectType(overrides: Partial<DefectType> = {}): DefectType {
  return {
    id: 2,
    code: "Q02",
    name: "Missing label",
    description: "",
    severity: "major",
    is_active: true,
    in_use: true,
    ...overrides,
  };
}

export const DEFECT_TYPES: DefectType[] = [
  makeDefectType({ id: 1, code: "Q01", name: "Empty or underfilled bottle" }),
  makeDefectType(),
  makeDefectType({ id: 3, code: "Q03", name: "Misaligned or wrinkled label", severity: "minor" }),
  makeDefectType({ id: 4, code: "Q04", name: "Missing or tilted cap", severity: "critical" }),
];

export function makeResult(overrides: Partial<InspectionResult> = {}): InspectionResult {
  return {
    id: 51,
    event_id: "00000000-0000-4000-8000-000000000051",
    line: 1,
    machine: { id: 5, external_id: "M05", name: "Labeler" },
    station: { id: 4, name: "Label and code check (labeler)" },
    timestamp: "2026-10-13T09:08:30Z",
    reported_code: "Q02",
    defect_type: { id: 2, code: "Q02", name: "Missing label", severity: "major" },
    effective_defect_type: { id: 2, code: "Q02", name: "Missing label", severity: "major" },
    is_defect: true,
    confidence: 0.91,
    source: "simulator",
    outcome: "rejected",
    warnings: [],
    review: null,
    context: {
      product: { id: 7, sku: "W050", name: "Water 0.5 L" },
      order_id: 3,
      machine_state: "running",
      machine_state_since: "2026-10-13T09:06:30Z",
      last_alarm_code: "E-204",
      last_alarm_at: "2026-10-13T09:05:00Z",
      incident: {
        id: 14,
        ended_at: "2026-10-13T09:06:30Z",
        seconds_after: 120,
        first_observed_stop: { machine: "Labeler", alarm_code: "E-204" },
        text: "Occurred 2 min after incident #14 ended (first observed stop: Labeler, E-204)",
      },
    },
    ...overrides,
  };
}

export function makeSummary(overrides: Partial<QualitySummary> = {}): QualitySummary {
  return {
    inspected_by_station: [
      {
        station: {
          id: 4,
          name: "Label and code check (labeler)",
          machine: { id: 5, external_id: "M05", name: "Labeler" },
          is_active: true,
        },
        inspected: 6000,
        defects: 120,
        defect_rate: 0.02,
      },
    ],
    defects_without_station: 0,
    line_total_count: 6000,
    line_counts: { counting_machine_output: 5880, counting_machine_rejected: 0, upstream_rejected: 120 },
    defects: 120,
    defect_rate: 0.02,
    defects_by_severity: { minor: 0, major: 120, critical: 0, unknown: 0 },
    false_rejects: 0,
    unreviewed: 118,
    results_with_warnings: 0,
    warnings: [],
    ...overrides,
  };
}

export function makeQualityPareto(overrides: Partial<QualityPareto> = {}): QualityPareto {
  return {
    group_by: "defect_type",
    total: 120,
    false_rejects_excluded: 2,
    groups: [
      { key: "defect_type:2", id: 2, label: "Q02 · Missing label", code: "Q02", severity: "major", count: 100, share: 0.8333, cumulative_share: 0.8333 },
      { key: "defect_type:none", id: null, label: "Unknown defect type", count: 20, share: 0.1667, cumulative_share: 1 },
    ],
    ...overrides,
  };
}

export const TREND: QualityTrend = {
  group_by: "hour",
  buckets: [
    { start: "2026-10-13T05:00:00Z", end: "2026-10-13T06:00:00Z", label: "2026-10-13 06:00", defects: 60, total_count: 3000, defect_rate: 0.02 },
    { start: "2026-10-13T06:00:00Z", end: "2026-10-13T07:00:00Z", label: "2026-10-13 07:00", defects: 60, total_count: 3000, defect_rate: 0.02 },
  ],
  total: { defects: 120, total_count: 6000, defect_rate: 0.02 },
};
