import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router";

import { listAlerts } from "../api/alerts.ts";
import { ALERT_SEVERITIES, RULE_TYPES } from "../api/alertTypes.ts";
import { listLines } from "../api/endpoints.ts";
import { queryKeys } from "../api/queryKeys.ts";
import { AlertCard } from "../components/alerts/AlertCard.tsx";
import { IncidentDrawer } from "../components/downtime/IncidentDrawer.tsx";
import { Panel } from "../components/Panel.tsx";
import { t } from "../i18n/t.ts";
import { ruleTypeLabel, severityLabel } from "../lib/alertText.ts";
import { usePermissions } from "../lib/permissions.ts";
import { useServerNow } from "../lib/serverClock.ts";

type Filter = "status" | "severity" | "type" | "line" | "incident";
const select = "rounded-lg border border-gray-300 bg-white px-3 py-2 text-lg";
const PAGE_SIZE = 50;

/** All alerts the user may see. Filters live in the URL (?status=&severity=&type=&line=). */
export function AlertsPage() {
  const [params, setParams] = useSearchParams();
  const nowMs = useServerNow();
  const { canResolveAlerts } = usePermissions();
  const highlighted = Number(params.get("alert")) || null;
  const drawerId = Number(params.get("incident")) || null;
  const query = {
    status: params.get("status") ?? "",
    severity: params.get("severity") ?? "",
    type: params.get("type") ?? "",
    line: params.get("line") ?? "",
    limit: PAGE_SIZE,
  };
  const alerts = useQuery({
    queryKey: queryKeys.alertList(query),
    queryFn: () => listAlerts(query),
    placeholderData: keepPreviousData,
    refetchInterval: 30_000,
  });
  const lines = useQuery({ queryKey: queryKeys.lines, queryFn: listLines });

  const setFilter = (name: Filter, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(name, value);
    else next.delete(name);
    setParams(next, { replace: true });
  };
  const zone = alerts.data?.results[0]?.factory_timezone ?? "UTC";

  return (
    <main className="flex min-h-screen flex-col gap-4 bg-gray-100 p-4">
      <h1 className="text-3xl font-bold">{t("alerts.title")}</h1>
      <section aria-label="Filters" className="flex flex-wrap items-center gap-3 rounded-xl bg-white p-4 shadow-sm">
        <label className="flex items-center gap-2 text-lg">
          {t("alerts.status")}
          <select value={query.status} onChange={(e) => setFilter("status", e.target.value)} className={select}>
            <option value="">{t("alerts.all")}</option>
            <option value="unresolved">{t("alerts.unresolved")}</option>
            <option value="open">{t("alertStatus.open")}</option>
            <option value="acknowledged">{t("alertStatus.acknowledged")}</option>
            <option value="resolved">{t("alertStatus.resolved")}</option>
          </select>
        </label>
        <label className="flex items-center gap-2 text-lg">
          {t("alerts.severity")}
          <select value={query.severity} onChange={(e) => setFilter("severity", e.target.value)} className={select}>
            <option value="">{t("alerts.all")}</option>
            {ALERT_SEVERITIES.map((s) => (
              <option key={s} value={s}>
                {severityLabel(s)}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-2 text-lg">
          {t("alerts.type")}
          <select value={query.type} onChange={(e) => setFilter("type", e.target.value)} className={select}>
            <option value="">{t("alerts.all")}</option>
            {RULE_TYPES.map((type) => (
              <option key={type} value={type}>
                {ruleTypeLabel(type)}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-2 text-lg">
          {t("alerts.line")}
          <select value={query.line} onChange={(e) => setFilter("line", e.target.value)} className={select}>
            <option value="">{t("alerts.all")}</option>
            {(lines.data ?? []).map((line) => (
              <option key={line.id} value={line.id}>
                {line.name}
              </option>
            ))}
          </select>
        </label>
      </section>

      <Panel isLoading={alerts.isLoading} isError={alerts.isError} isEmpty={alerts.data?.results.length === 0} emptyText={t("alerts.empty")}>
        <div className="flex flex-col gap-3">
          {(alerts.data?.results ?? []).map((alert) => (
            <AlertCard
              key={alert.id}
              alert={alert}
              nowMs={nowMs}
              canResolve={canResolveAlerts}
              highlighted={alert.id === highlighted}
              onOpenIncident={(id) => setFilter("incident", String(id))}
            />
          ))}
        </div>
      </Panel>
      {drawerId !== null && <IncidentDrawer incidentId={drawerId} zone={zone} onClose={() => setFilter("incident", "")} />}
    </main>
  );
}
