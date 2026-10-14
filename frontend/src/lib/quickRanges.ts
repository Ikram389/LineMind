import type { ShiftOccurrence } from "../api/analysisTypes.ts";
import type { CurrentShift } from "../api/types.ts";
import { localDate, nextDate, zonedMidnight } from "./zonedTime.ts";

export type QuickRange = "currentShift" | "lastShift" | "today" | "yesterday" | "last7";

const DAY = 86_400_000;

export interface Range {
  start: string;
  end: string;
}

const iso = (ms: number) => new Date(ms).toISOString();

/** A quick-pick range, with days measured in the factory's timezone. */
export function quickRange(
  kind: QuickRange,
  ctx: {
    nowMs: number;
    zone: string;
    currentShift: CurrentShift | null;
    previousShifts: ShiftOccurrence[];
  },
): Range {
  const today = localDate(ctx.nowMs, ctx.zone);
  const day = (date: string): Range => ({
    start: iso(zonedMidnight(date, ctx.zone)),
    end: iso(zonedMidnight(nextDate(date), ctx.zone)),
  });

  switch (kind) {
    case "currentShift":
      return ctx.currentShift
        ? { start: ctx.currentShift.start, end: ctx.currentShift.end }
        : day(today);
    case "lastShift": {
      const before = ctx.currentShift ? Date.parse(ctx.currentShift.start) : ctx.nowMs;
      const last = [...ctx.previousShifts]
        .filter((o) => Date.parse(o.end) <= before)
        .sort((a, b) => Date.parse(b.end) - Date.parse(a.end))[0];
      return last ? { start: last.start, end: last.end } : day(nextDate(today, -1));
    }
    case "today":
      return day(today);
    case "yesterday":
      return day(nextDate(today, -1));
    case "last7":
      return { start: iso(ctx.nowMs - 7 * DAY), end: iso(ctx.nowMs) };
  }
}
