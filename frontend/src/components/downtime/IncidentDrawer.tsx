import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";

import { getIncident } from "../../api/downtime.ts";
import { CreateActionButton } from "../maintenance/CreateActionDialog.tsx";
import { queryKeys } from "../../api/queryKeys.ts";
import type { MessageKey } from "../../i18n/en.ts";
import { t } from "../../i18n/t.ts";
import { formatDateTime, formatDuration } from "../../lib/time.ts";

const CATEGORY_KEY: Record<string, MessageKey> = {
  breakdown: "category.breakdown",
  blocked: "category.blocked",
  starved: "category.starved",
  planned: "category.planned",
  no_data: "category.no_data",
};

const ROLE_STYLE: Record<string, string> = {
  first_observed_stop: "border-red-700 bg-red-50",
  secondary_breakdown: "border-orange-500 bg-orange-50",
  consequence: "border-gray-300 bg-white",
};

/** One line stop, in time order: first observed stop at the top, then what followed. */
export function IncidentDrawer({ incidentId, zone, onClose }: { incidentId: number; zone: string; onClose: () => void }) {
  const incident = useQuery({
    queryKey: queryKeys.incident(incidentId),
    queryFn: () => getIncident(incidentId),
  });

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/40" role="presentation">
      <aside
        role="dialog"
        aria-modal="true"
        aria-labelledby="drawer-title"
        className="h-full w-full max-w-xl overflow-y-auto bg-gray-50 p-5 shadow-2xl"
      >
        <header className="mb-4 flex items-start justify-between">
          <div>
            <h2 id="drawer-title" className="text-2xl font-bold">
              {t("drawer.title", { id: incidentId })}
            </h2>
            {incident.data && (
              <p className="text-lg text-gray-700">
                {formatDateTime(incident.data.started_at, zone)} · {formatDuration(incident.data.duration_seconds)}
              </p>
            )}
            <div className="mt-2">
              <CreateActionButton source={{ source: "incident", id: incidentId }} />
            </div>
          </div>
          <button type="button" onClick={onClose} aria-label={t("drawer.close")} className="p-2">
            <X aria-hidden className="h-8 w-8" />
          </button>
        </header>

        {incident.isLoading && <p className="text-lg">{t("panel.loading")}</p>}
        {incident.isError && <p className="text-lg text-red-700">{t("panel.error")}</p>}

        {incident.data && (
          <>
            <h3 className="mb-2 text-lg font-semibold">{t("drawer.cascade")}</h3>
            <ol className="flex flex-col gap-3">
              {incident.data.events.map((member) => (
                <li
                  key={member.id}
                  data-role={member.role_in_incident ?? ""}
                  className={`rounded-lg border-2 p-3 ${ROLE_STYLE[member.role_in_incident ?? "consequence"] ?? ""}`}
                >
                  <p className="text-xl font-semibold">
                    {member.machine.name} · {t(CATEGORY_KEY[member.category] ?? "category.breakdown")}
                    {member.alarm_code && ` · ${member.alarm_code}`}
                  </p>
                  <p className="text-base font-bold uppercase">
                    {member.role_in_incident && t(`role.${member.role_in_incident}` as MessageKey)}
                  </p>
                  <p className="text-lg text-gray-700">
                    {member.delay_seconds > 0 && `${t("drawer.delay", { delay: formatDuration(member.delay_seconds) })} · `}
                    {formatDuration(member.duration_seconds)}
                  </p>
                  {member.role_in_incident !== "consequence" && (
                    <div className="mt-1 text-base text-gray-700">
                      <span className="font-semibold">{t("drawer.history")}: </span>
                      {member.classifications.length === 0
                        ? t("drawer.noHistory")
                        : member.classifications
                            .map((c) => `${c.reason.name} (${c.created_by ?? "—"}, ${formatDateTime(c.created_at, zone)})`)
                            .join(" → ")}
                    </div>
                  )}
                </li>
              ))}
            </ol>
          </>
        )}
      </aside>
    </div>
  );
}
