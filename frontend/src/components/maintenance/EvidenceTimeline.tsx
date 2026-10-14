import { CircleAlert, CircleX, Diamond, OctagonPause, Square } from "lucide-react";
import { Link } from "react-router";

import type { ActionLink, MaintenanceAction } from "../../api/maintenanceTypes.ts";
import { t } from "../../i18n/t.ts";
import { alertMessage } from "../../lib/alertText.ts";
import { formatDateTime } from "../../lib/time.ts";

function when(link: ActionLink): string {
  const target = link.target;
  return String(target.started_at ?? target.timestamp ?? target.opened_at ?? link.created_at);
}

/** What the action is about, in time order, with links to each record's screen. */
export function EvidenceTimeline({
  action,
  links,
  onOpenIncident,
}: {
  action: MaintenanceAction;
  links: ActionLink[];
  onOpenIncident: (id: number) => void;
}) {
  const zone = action.factory_timezone;
  const signature = links.find((l) => l.kind === "signature");
  const others = links.filter((l) => l.kind !== "signature").sort((a, b) => Date.parse(when(a)) - Date.parse(when(b)));
  if (links.length === 0) return <p className="text-lg text-gray-600">{t("maint.evidence.empty")}</p>;

  return (
    <ol className="flex flex-col gap-2" data-testid="evidence">
      {signature && (
        <li className="flex items-center gap-2 rounded-lg bg-amber-50 p-2 text-lg font-semibold">
          <Diamond aria-hidden className="h-5 w-5 shrink-0" />
          {t("maint.evidence.signature", {
            machine: (signature.target.machine as { name: string }).name,
            what: String(
              (signature.target.reason as { name?: string } | null)?.name ?? signature.target.alarm_code ?? "",
            ),
          })}
        </li>
      )}
      {others.map((link) => {
        const target = link.target;
        const time = formatDateTime(when(link), zone);
        if (link.kind === "downtime_event") {
          return (
            <li key={link.id} className="flex flex-wrap items-center gap-2 text-lg">
              <Square aria-hidden className="h-4 w-4 shrink-0 text-red-700" />
              {t("maint.evidence.stop", {
                machine: String(target.machine),
                time,
                alarm: target.alarm_code ? `, ${String(target.alarm_code)}` : "",
              })}
              {typeof target.incident_id === "number" && (
                <button type="button" onClick={() => onOpenIncident(target.incident_id as number)} className="text-blue-800 underline">
                  {t("maint.evidence.open")}
                </button>
              )}
            </li>
          );
        }
        if (link.kind === "incident") {
          return (
            <li key={link.id} className="flex flex-wrap items-center gap-2 text-lg">
              <OctagonPause aria-hidden className="h-5 w-5 shrink-0 text-red-800" />
              {t("maint.evidence.incident", { id: target.id ?? "", time })}
              <button type="button" onClick={() => onOpenIncident(target.id as number)} className="text-blue-800 underline">
                {t("maint.evidence.open")}
              </button>
            </li>
          );
        }
        if (link.kind === "alert") {
          return (
            <li key={link.id} className="flex flex-wrap items-center gap-2 text-lg">
              <CircleAlert aria-hidden className="h-5 w-5 shrink-0 text-amber-700" />
              {t("maint.evidence.alert", { time })}: {alertMessage(String(target.message_key), (target.message_values ?? {}) as Record<string, string>)}
              <Link to={`/alerts?alert=${target.id}`} className="text-blue-800 underline">
                {t("maint.evidence.open")}
              </Link>
            </li>
          );
        }
        return (
          <li key={link.id} className="flex flex-wrap items-center gap-2 text-lg">
            <CircleX aria-hidden className="h-5 w-5 shrink-0 text-orange-700" />
            {t("maint.evidence.defect", { code: String(target.reported_code), machine: String(target.machine), time })}
            <Link to={`/lines/${action.line}/quality`} className="text-blue-800 underline">
              {t("maint.evidence.open")}
            </Link>
          </li>
        );
      })}
    </ol>
  );
}
