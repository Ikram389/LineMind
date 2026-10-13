import type { DowntimeCategory, DowntimeEvent, MachineState } from "../api/types.ts";

export interface Segment {
  state: MachineState;
  startMs: number;
  endMs: number;
  alarm: string | null;
}

const CATEGORY_STATE: Record<DowntimeCategory, MachineState> = {
  breakdown: "stopped",
  blocked: "blocked",
  starved: "starved",
  planned: "planned_stop",
  no_data: "unknown",
};

/**
 * The machine's states between `fromMs` and `toMs`, from its downtime events:
 * every downtime event is a coloured segment, the time between them is "running",
 * and time after the data went stale (or before any data) is "unknown".
 */
export function buildTimeline(
  downtime: DowntimeEvent[],
  fromMs: number,
  toMs: number,
  knownUntilMs: number | null,
): Segment[] {
  const knownEnd = Math.min(toMs, knownUntilMs ?? fromMs);
  const stops = downtime
    .map((event) => ({
      state: CATEGORY_STATE[event.category],
      startMs: Math.max(fromMs, Date.parse(event.started_at)),
      endMs: Math.min(knownEnd, event.ended_at ? Date.parse(event.ended_at) : knownEnd),
      alarm: event.alarm_code,
    }))
    .filter((s) => s.endMs > s.startMs)
    .sort((a, b) => a.startMs - b.startMs);

  const segments: Segment[] = [];
  let cursor = fromMs;
  for (const stop of stops) {
    if (stop.startMs > cursor) {
      segments.push({ state: "running", startMs: cursor, endMs: stop.startMs, alarm: null });
    }
    const startMs = Math.max(cursor, stop.startMs);
    if (stop.endMs > startMs) segments.push({ ...stop, startMs });
    cursor = Math.max(cursor, stop.endMs);
  }
  if (knownEnd > cursor) {
    segments.push({ state: "running", startMs: cursor, endMs: knownEnd, alarm: null });
  }
  if (toMs > Math.max(cursor, knownEnd)) {
    segments.push({ state: "unknown", startMs: Math.max(cursor, knownEnd), endMs: toMs, alarm: null });
  }
  return segments;
}
