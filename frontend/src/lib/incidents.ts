import type { Incident } from "../api/types.ts";
import { t } from "../i18n/t.ts";
import { formatDuration, secondsBetween } from "./time.ts";

/** "Line stopped for 3 min 12 s — first observed stop: Labeler (alarm E-204)" */
export function incidentHeadline(incident: Incident, nowMs: number): string {
  const duration = formatDuration(secondsBetween(incident.started_at, nowMs));
  const firsts = incident.first_observed_stop.machines;
  if (incident.origin === "unknown" || firsts.length === 0) {
    return t("incident.unknownOrigin", { duration });
  }
  const alarm = incident.first_observed_stop.alarm_code;
  const machines =
    firsts.map((m) => m.name).join(" + ") +
    (alarm ? ` ${t("incident.alarm", { code: alarm })}` : "");
  return t("incident.stopped", { duration, machines });
}
