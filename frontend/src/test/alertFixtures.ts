import type { Alert, RuleTypeInfo } from "../api/alertTypes.ts";

export function makeAlert(overrides: Partial<Alert> = {}): Alert {
  return {
    id: 31,
    rule: { id: 2, rule_type: "long_stop", name: "Long line stop" },
    factory: 1,
    factory_timezone: "Africa/Algiers",
    line: { id: 1, name: "Bottling Line 1" },
    machine: { id: 5, name: "Labeler" },
    subject: { type: "incident", id: 14, key: "incident:14" },
    severity: "warning",
    status: "open",
    opened_at: "2026-10-14T09:06:00Z",
    condition_since: "2026-10-14T09:05:00Z",
    message_key: "alert.long_stop",
    message_values: { machine: "Labeler", minutes: 1, alarm: "E-204", line: "Bottling Line 1", incident_id: 14 },
    acknowledged_by: null,
    acknowledged_at: null,
    acknowledge_note: "",
    resolved_at: null,
    resolution: "",
    resolved_by: null,
    resolution_note: "",
    escalated_at: null,
    last_evaluated_at: "2026-10-14T09:06:30Z",
    can_acknowledge: true,
    ...overrides,
  };
}

const integer = (name: string, min: number, max: number | null, value: number | null) => ({
  name, kind: "integer", required: false, default: value, min, max, choices: null, help: "",
});

export const RULE_TYPES_INFO: RuleTypeInfo[] = [
  {
    type: "long_stop",
    time_driven: true,
    machine_scoped: true,
    parameters: [
      integer("minutes", 1, 1440, null),
      { name: "scope", kind: "choice", required: false, default: "incident", min: null, max: null, choices: ["incident", "breakdown"], help: "" },
    ],
  },
  {
    type: "low_oee",
    time_driven: true,
    machine_scoped: false,
    parameters: [
      { name: "below_percent", kind: "float", required: false, default: 60, min: 1, max: 100, choices: null, help: "" },
      integer("min_planned_minutes", 1, 1440, 60),
    ],
  },
];
