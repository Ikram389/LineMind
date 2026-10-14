import type { Effectiveness, MaintenanceAction } from "../api/maintenanceTypes.ts";

export function makeAction(overrides: Partial<MaintenanceAction> = {}): MaintenanceAction {
  return {
    id: 12,
    factory: 1,
    line: 1,
    line_name: "Bottling Line 1",
    machine: 5,
    machine_name: "Labeler",
    factory_timezone: "Africa/Algiers",
    title: "Labeler · E-204: recurring stops",
    problem: "Labeler stopped 7 times for E-204",
    action_type: "corrective",
    priority: "high",
    status: "in_progress",
    reporter: { id: 3, email: "production_supervisor@demo.test" },
    assignee: 9,
    assignee_detail: { id: 9, email: "maintenance_technician@demo.test" },
    due_date: "2026-10-20",
    is_overdue: false,
    started_at: "2026-10-14T08:00:00Z",
    completed_at: null,
    fixed_at: null,
    verified_by: null,
    verified_at: null,
    verification_result: "",
    verification_note: "",
    effectiveness_window_days: 7,
    min_after_run_hours: 20,
    created_at: "2026-10-14T07:00:00Z",
    updated_at: "2026-10-14T08:00:00Z",
    allowed_steps: [
      { to: "waiting", event: "wait", note_required: true },
      { to: "done", event: "complete", note_required: false },
    ],
    link_count: 3,
    ...overrides,
  };
}

const window = (occurrences: number, perTen: number) => ({
  start: "2026-09-28T05:00:00Z",
  end: "2026-10-05T05:00:00Z",
  occurrences,
  downtime_seconds: occurrences * 90,
  run_hours: 150,
  occurrences_per_10h: perTen,
  downtime_minutes_per_10h: perTen * 1.5,
});

export function makeEffect(overrides: Partial<Effectiveness> = {}): Effectiveness {
  return {
    status: "improved",
    fixed_at: "2026-10-05T05:00:00Z",
    window_days: 7,
    min_after_run_hours: 20,
    min_before_occurrences: 5,
    signature: { machine: { id: 5, name: "Labeler" }, reason: null, alarm_code: "E-204" },
    before: window(180, 12),
    after: window(18, 1.18),
    message_key: "effect.fell",
    message_values: { from: 12, to: 1.18 },
    ...overrides,
  };
}
