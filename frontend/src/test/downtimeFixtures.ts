import type {
  AnalysedDowntimeEvent,
  IncidentMember,
  ParetoResponse,
  Reason,
} from "../api/analysisTypes.ts";

export function makeReason(overrides: Partial<Reason> = {}): Reason {
  return {
    id: 1,
    factory: 1,
    code: "MECH-JAM",
    name: "Jam / blockage",
    category: "mechanical",
    is_active: true,
    is_changeover: false,
    in_use: false,
    ...overrides,
  };
}

export const REASONS: Reason[] = [
  makeReason({ id: 1, code: "MECH-JAM", name: "Jam / blockage", category: "mechanical" }),
  makeReason({ id: 2, code: "ELEC-SENSOR", name: "Sensor fault", category: "electrical" }),
  makeReason({ id: 3, code: "MAT-LABEL", name: "Label roll empty", category: "material" }),
  makeReason({ id: 4, code: "PLAN-BREAK", name: "Break", category: "planned" }),
  makeReason({ id: 5, code: "ORG-OPERATOR", name: "Operator absent", category: "organizational" }),
];

export function makeEvent(overrides: Partial<AnalysedDowntimeEvent> = {}): AnalysedDowntimeEvent {
  return {
    id: 11,
    machine: { id: 5, external_id: "M05", name: "Labeler", position: 5 },
    line: 1,
    category: "breakdown",
    state: "stopped",
    started_at: "2026-10-13T09:05:00Z",
    ended_at: "2026-10-13T09:08:12Z",
    duration_seconds: 192,
    is_ongoing: false,
    alarm_code: "E-204",
    is_first_stop: true,
    incident: 7,
    classification: null,
    role_in_incident: "first_observed_stop",
    clipped_duration_seconds: 192,
    ...overrides,
  };
}

export function makeMember(overrides: Partial<IncidentMember> = {}): IncidentMember {
  return { ...makeEvent(), delay_seconds: 0, classifications: [], ...overrides };
}

export function makePareto(overrides: Partial<ParetoResponse> = {}): ParetoResponse {
  return {
    view: "line",
    view_note: "Line view: each line stop is counted once and attributed to its first observed stop.",
    group_by: "reason",
    total_seconds: 300,
    total_occurrences: 3,
    estimated_lost_units: { units: 500, is_estimate: true, basis: "…" },
    groups: [
      {
        key: "unclassified",
        label: "Unclassified",
        total_seconds: 200,
        total_micros: 200_000_000,
        occurrences: 2,
        estimated_lost_units: { units: 333, is_estimate: true, basis: "…" },
        share: 0.6667,
        cumulative_share: 0.6667,
      },
      {
        key: "reason:1",
        label: "MECH-JAM · Jam / blockage",
        total_seconds: 100,
        total_micros: 100_000_000,
        occurrences: 1,
        estimated_lost_units: { units: 167, is_estimate: true, basis: "…" },
        share: 0.3333,
        cumulative_share: 1,
      },
    ],
    ...overrides,
  };
}
