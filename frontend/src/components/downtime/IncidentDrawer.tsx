import { useQuery } from "@tanstack/react-query";

import { getIncident } from "../../api/downtime.ts";
import { queryKeys } from "../../api/queryKeys.ts";
import { t } from "../../i18n/t.ts";
import { cn } from "../../lib/cn.ts";
import { formatDateTime, formatDuration } from "../../lib/time.ts";
import { CreateActionButton } from "../maintenance/CreateActionDialog.tsx";
import { ErrorState, Skeleton } from "../ui/Feedback.tsx";
import { Drawer } from "../ui/Overlay.tsx";
import { RoleBadge } from "./badges.tsx";
import { CATEGORY_KEY } from "./categories.ts";

const ROLE_BORDER: Record<string, string> = {
  first_observed_stop: "border-l-critical",
  secondary_breakdown: "border-l-warning",
  consequence: "border-l-line-strong",
};

/** One line stop, in time order: first observed stop at the top, then what followed. */
export function IncidentDrawer({ incidentId, zone, onClose }: { incidentId: number; zone: string; onClose: () => void }) {
  const incident = useQuery({
    queryKey: queryKeys.incident(incidentId),
    queryFn: () => getIncident(incidentId),
  });

  return (
    <Drawer
      title={t("drawer.title", { id: incidentId })}
      subtitle={
        incident.data &&
        t("drawer.subtitle", {
          time: formatDateTime(incident.data.started_at, zone),
          duration: formatDuration(incident.data.duration_seconds),
        })
      }
      onClose={onClose}
    >
      <div className="flex flex-col gap-4">
        <div>
          <CreateActionButton source={{ source: "incident", id: incidentId }} />
        </div>
        {incident.isLoading && <Skeleton lines={4} />}
        {incident.isError && <ErrorState />}
        {incident.data && (
          <section className="flex flex-col gap-3">
            <h3 className="text-body font-semibold text-ink">{t("drawer.cascade")}</h3>
            <ol className="flex flex-col gap-3">
              {incident.data.events.map((member) => (
                <li
                  key={member.id}
                  data-role={member.role_in_incident ?? ""}
                  className={cn(
                    "flex flex-col gap-2 rounded-card border border-l-4 border-line bg-surface p-4",
                    ROLE_BORDER[member.role_in_incident ?? "consequence"],
                  )}
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="text-body font-semibold text-ink">
                      {member.machine.name} · {t(CATEGORY_KEY[member.category] ?? "category.breakdown")}
                      {member.alarm_code && ` · ${member.alarm_code}`}
                    </p>
                    <RoleBadge role={member.role_in_incident} />
                  </div>
                  <p className="text-small tabular-nums text-ink-muted">
                    {member.delay_seconds > 0 &&
                      `${t("drawer.delay", { delay: formatDuration(member.delay_seconds) })} · `}
                    {formatDuration(member.duration_seconds)}
                  </p>
                  {member.role_in_incident !== "consequence" && (
                    <p className="text-small text-ink-muted">
                      <span className="font-semibold text-ink">{t("drawer.history")}: </span>
                      {member.classifications.length === 0
                        ? t("drawer.noHistory")
                        : member.classifications
                            .map((c) => `${c.reason.name} (${c.created_by ?? "—"}, ${formatDateTime(c.created_at, zone)})`)
                            .join(" → ")}
                    </p>
                  )}
                </li>
              ))}
            </ol>
          </section>
        )}
      </div>
    </Drawer>
  );
}
