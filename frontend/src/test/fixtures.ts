import type { Incident, LineStatus, MachineStatus } from "../api/types.ts";

/** Server "now" used by most tests: 2026-10-13 12:00:00 UTC. */
export const NOW_MS = Date.parse("2026-10-13T12:00:00Z");

export const iso = (msAgo: number): string => new Date(NOW_MS - msAgo).toISOString();

export function makeMachine(overrides: Partial<MachineStatus> = {}): MachineStatus {
  return {
    id: 5,
    external_id: "M05",
    name: "Labeler",
    position: 5,
    state: "running",
    reported_state: "running",
    state_since: iso(192_000), // 3 min 12 s ago
    alarm_code: null,
    last_alarm_code: null,
    last_alarm_at: null,
    is_stale: false,
    last_seen: iso(2_000),
    shift_count: 15_100,
    shift_rejected: 12,
    last_count: { count: 15_100, rejected: 12, timestamp: iso(2_000) },
    ...overrides,
  };
}

export function makeIncident(overrides: Partial<Incident> = {}): Incident {
  return {
    incident_id: 7,
    started_at: iso(192_000),
    ended_at: null,
    origin: "machine_stop",
    first_observed_stop: {
      machines: [{ id: 5, external_id: "M05", name: "Labeler" }],
      alarm_code: "E-204",
    },
    affected_machines: [
      { id: 5, external_id: "M05", name: "Labeler", category: "breakdown", started_at: iso(192_000), ended_at: null, is_first_stop: true },
      { id: 4, external_id: "M04", name: "Capper", category: "blocked", started_at: iso(189_000), ended_at: null, is_first_stop: false },
      { id: 6, external_id: "M06", name: "Packer", category: "starved", started_at: iso(184_000), ended_at: null, is_first_stop: false },
    ],
    ...overrides,
  };
}

export function makeStatus(machines: MachineStatus[], incident: Incident | null = null): LineStatus {
  return {
    line: { id: 1, name: "Bottling Line 1" },
    factory_timezone: "Africa/Algiers",
    stale_after_seconds: 60,
    generated_at: iso(0),
    current_shift_start: iso(6 * 3600_000),
    machines,
    open_incident: incident,
  };
}
