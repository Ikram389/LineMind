import { t } from "../i18n/t.ts";

const pad = (n: number): string => String(n).padStart(2, "0");

/** 0 s · 59 s · 3 min 12 s · 1 h 02 min · 2 d 3 h */
export function formatDuration(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds));
  if (s < 60) return t("duration.seconds", { s });
  if (s < 3600) return t("duration.minutes", { m: Math.floor(s / 60), s: s % 60 });
  if (s < 86_400) {
    return t("duration.hours", { h: Math.floor(s / 3600), mm: pad(Math.floor((s % 3600) / 60)) });
  }
  return t("duration.days", { d: Math.floor(s / 86_400), h: Math.floor((s % 86_400) / 3600) });
}

/** Like formatDuration but without seconds once past a minute: "42 min", "1 h 05 min". */
export function formatShortDuration(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds));
  if (s < 60) return t("duration.seconds", { s });
  if (s < 3600) return t("duration.shortMinutes", { m: Math.floor(s / 60) });
  return formatDuration(s);
}

export function secondsBetween(fromIso: string, nowMs: number): number {
  return (nowMs - Date.parse(fromIso)) / 1000;
}

function formatter(zone: string, withSeconds: boolean): Intl.DateTimeFormat {
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: zone,
    hour: "2-digit",
    minute: "2-digit",
    second: withSeconds ? "2-digit" : undefined,
    hour12: false,
  });
}

/** Clock time in the factory's timezone, e.g. "13:46:05". */
export function formatClock(value: Date | string | number, zone: string): string {
  return formatter(zone, true).format(new Date(value));
}

/** Hours and minutes in the factory's timezone, e.g. "06:00". */
export function formatTime(value: Date | string | number, zone: string): string {
  return formatter(zone, false).format(new Date(value));
}

/** Short date and time in the factory's timezone, e.g. "13 Oct 10:05". */
export function formatDateTime(value: Date | string | number, zone: string): string {
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: zone,
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(value));
}
