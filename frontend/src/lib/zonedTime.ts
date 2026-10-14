/** Calendar days in a factory's timezone, independent of the device's own timezone. */

function partsIn(zone: string, ms: number): Record<string, number> {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: zone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).formatToParts(new Date(ms));
  const out: Record<string, number> = {};
  for (const part of parts) {
    if (part.type !== "literal") out[part.type] = Number(part.value);
  }
  return out;
}

/** The zone's offset from UTC at that instant, in milliseconds. */
function offsetMs(zone: string, ms: number): number {
  const p = partsIn(zone, ms);
  const asUtc = Date.UTC(p.year ?? 0, (p.month ?? 1) - 1, p.day ?? 1, (p.hour ?? 0) % 24, p.minute ?? 0, p.second ?? 0);
  return asUtc - Math.floor(ms / 1000) * 1000;
}

/** "YYYY-MM-DD" of the instant in the zone. */
export function localDate(ms: number, zone: string): string {
  const p = partsIn(zone, ms);
  const pad = (n: number | undefined) => String(n ?? 0).padStart(2, "0");
  return `${p.year}-${pad(p.month)}-${pad(p.day)}`;
}

/** The UTC instant (ms) of a wall-clock time ("YYYY-MM-DD", "HH:mm") in the zone. */
export function zonedTimeToUtc(date: string, time: string, zone: string): number {
  const [y, m, d] = date.split("-").map(Number);
  const [hh, mm] = time.split(":").map(Number);
  const guess = Date.UTC(y ?? 1970, (m ?? 1) - 1, d ?? 1, hh ?? 0, mm ?? 0);
  // Two passes handle times right after a daylight-saving change.
  const first = guess - offsetMs(zone, guess);
  return guess - offsetMs(zone, first);
}

/** The UTC instant (ms) of local midnight at the start of `date` ("YYYY-MM-DD") in the zone. */
export function zonedMidnight(date: string, zone: string): number {
  return zonedTimeToUtc(date, "00:00", zone);
}

/** "YYYY-MM-DDTHH:mm" in the zone (the value format of <input type="datetime-local">). */
export function toLocalInput(iso: string, zone: string): string {
  const ms = Date.parse(iso);
  const p = partsIn(zone, ms);
  const pad = (n: number | undefined) => String(n ?? 0).padStart(2, "0");
  return `${localDate(ms, zone)}T${pad((p.hour ?? 0) % 24)}:${pad(p.minute)}`;
}

/** A datetime-local value in the zone, as a UTC ISO string. */
export function fromLocalInput(value: string, zone: string): string | null {
  const [date, time] = value.split("T");
  if (!date || !time) return null;
  return new Date(zonedTimeToUtc(date, time, zone)).toISOString();
}

/** "YYYY-MM-DD" of the day after `date`. */
export function nextDate(date: string, days = 1): string {
  const [y, m, d] = date.split("-").map(Number);
  const next = new Date(Date.UTC(y ?? 1970, (m ?? 1) - 1, (d ?? 1) + days));
  return next.toISOString().slice(0, 10);
}
