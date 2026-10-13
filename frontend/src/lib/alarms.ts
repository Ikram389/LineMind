import type { MachineStatus } from "../api/types.ts";

/**
 * Which alarm a machine card shows:
 * - stopped with an alarm: that alarm, prominently ("current");
 * - otherwise the last alarm, small and muted with how long ago ("last"),
 *   but only if it happened during the current shift;
 * - otherwise nothing (an old alarm on a running machine is misleading).
 */
export function alarmToShow(
  machine: Pick<MachineStatus, "alarm_code" | "last_alarm_code" | "last_alarm_at">,
  state: string,
  shiftStart: string | null,
): { kind: "current"; code: string } | { kind: "last"; code: string; at: string } | null {
  if (state === "stopped" && machine.alarm_code) return { kind: "current", code: machine.alarm_code };
  if (
    machine.last_alarm_code &&
    machine.last_alarm_at &&
    shiftStart &&
    Date.parse(machine.last_alarm_at) >= Date.parse(shiftStart)
  ) {
    return { kind: "last", code: machine.last_alarm_code, at: machine.last_alarm_at };
  }
  return null; // no alarm, or older than the current shift
}
