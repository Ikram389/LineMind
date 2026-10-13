import { useEffect, useState } from "react";

/**
 * Server time, corrected for a wrong device clock.
 *
 * A factory tablet's clock can be minutes off. "Time in state" counters and stale
 * detection must use the server's clock, so we keep an offset (server - device):
 * - precisely from the `sent_at` of every WebSocket message (milliseconds),
 * - roughly from the `Date` header of API responses (whole seconds), which is only
 *   used when it disagrees with the current offset by more than 1.5 s.
 */
let offsetMs = 0;
let hasPreciseSample = false;

export function serverNow(): number {
  return Date.now() + offsetMs;
}

export function clockOffsetMs(): number {
  return offsetMs;
}

/** A precise server timestamp (e.g. a WebSocket message's sent_at). */
export function recordServerTime(serverMs: number, deviceMs: number = Date.now()): void {
  if (Number.isNaN(serverMs)) return;
  offsetMs = serverMs - deviceMs;
  hasPreciseSample = true;
}

/** An HTTP Date header (one-second precision). */
export function recordDateHeader(header: string | null, deviceMs: number = Date.now()): void {
  if (!header) return;
  const serverMs = Date.parse(header);
  if (Number.isNaN(serverMs)) return;
  const sample = serverMs + 500 - deviceMs; // the header is rounded down to the second
  if (!hasPreciseSample || Math.abs(sample - offsetMs) > 1500) {
    offsetMs = sample;
  }
}

/** For tests. */
export function resetServerClock(): void {
  offsetMs = 0;
  hasPreciseSample = false;
}

/** Server time that re-renders the component every `intervalMs`. */
export function useServerNow(intervalMs = 1000): number {
  const [now, setNow] = useState(serverNow);
  useEffect(() => {
    const id = window.setInterval(() => setNow(serverNow()), intervalMs);
    return () => window.clearInterval(id);
  }, [intervalMs]);
  return now;
}
