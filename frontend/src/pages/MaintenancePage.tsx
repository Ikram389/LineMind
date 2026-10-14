import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { AlarmClock, ArrowUp, ChevronsUp, Download, Minus } from "lucide-react";
import { useState } from "react";
import { Link, useSearchParams } from "react-router";

import { listLines } from "../api/endpoints.ts";
import { exportActionsCsv, listActions } from "../api/maintenance.ts";
import { ACTION_STATUSES, type MaintenanceAction, PRIORITIES, type Priority } from "../api/maintenanceTypes.ts";
import { queryKeys } from "../api/queryKeys.ts";
import { Panel } from "../components/Panel.tsx";
import { t } from "../i18n/t.ts";
import { PRIORITY_STYLE, priorityLabel, STATUS_STYLE, statusLabel } from "../lib/maintenanceText.ts";
import { usePermissions } from "../lib/permissions.ts";

const PRIORITY_ICON: Record<Priority, typeof ArrowUp> = { urgent: ChevronsUp, high: ArrowUp, medium: Minus, low: Minus };
const select = "rounded-lg border border-gray-300 bg-white px-3 py-2 text-lg";

function ActionRow({ action }: { action: MaintenanceAction }) {
  const PriorityIcon = PRIORITY_ICON[action.priority];
  return (
    <li data-testid={`action-${action.id}`} className={`rounded-xl border-l-8 bg-white p-4 shadow-sm ${action.is_overdue ? "border-red-700" : "border-gray-300"}`}>
      <div className="flex flex-wrap items-center gap-2">
        {action.is_overdue && (
          <span className="inline-flex items-center gap-1 rounded bg-red-700 px-2 py-1 text-base font-bold text-white">
            <AlarmClock aria-hidden className="h-5 w-5" />
            {t("maint.overdue")}
          </span>
        )}
        <span className={`inline-flex items-center gap-1 rounded px-2 py-1 text-base font-bold ${PRIORITY_STYLE[action.priority]}`}>
          <PriorityIcon aria-hidden className="h-5 w-5" />
          {priorityLabel(action.priority)}
        </span>
        <span className={`rounded px-2 py-1 text-base font-semibold ${STATUS_STYLE[action.status]}`}>{statusLabel(action.status)}</span>
        <Link to={`/maintenance/${action.id}`} className="text-xl font-bold text-blue-900 underline">
          #{action.id} {action.title}
        </Link>
      </div>
      <p className="mt-1 text-lg text-gray-700">
        {action.machine_name} · {action.line_name} ·{" "}
        {action.due_date ? t("maint.due", { date: action.due_date }) : t("maint.noDue")} ·{" "}
        {action.assignee_detail ? t("maint.assignee", { who: action.assignee_detail.email }) : t("maint.unassigned")} ·{" "}
        {t("maint.reportedBy", { who: action.reporter.email })} · {t("maint.links", { count: action.link_count })}
      </p>
    </li>
  );
}

/** All maintenance actions the user may see; technicians start on "My actions". */
export function MaintenancePage() {
  const { isTechnician } = usePermissions();
  const [params, setParams] = useSearchParams();
  const [exportError, setExportError] = useState(false);
  const mine = params.get("mine") ?? (isTechnician ? "true" : "false");
  const query = {
    mine: mine === "true" ? "true" : "",
    status: params.get("status") ?? "open",
    priority: params.get("priority") ?? "",
    line: params.get("line") ?? "",
    overdue: params.get("overdue") ?? "",
    limit: 100,
  };
  const actions = useQuery({
    queryKey: queryKeys.maintenanceList(query),
    queryFn: () => listActions(query),
    placeholderData: keepPreviousData,
  });
  const lines = useQuery({ queryKey: queryKeys.lines, queryFn: listLines });
  const set = (name: string, value: string) => {
    const next = new URLSearchParams(params);
    next.set(name, value);
    setParams(next, { replace: true });
  };

  async function exportCsv() {
    setExportError(false);
    try {
      const blob = await exportActionsCsv({ ...query, limit: undefined });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "maintenance-actions.csv";
      link.click();
      URL.revokeObjectURL(url);
    } catch {
      setExportError(true);
    }
  }

  return (
    <main className="flex min-h-screen flex-col gap-4 bg-gray-100 p-4">
      <h1 className="text-3xl font-bold">{t("maint.title")}</h1>
      <section aria-label="Filters" className="flex flex-wrap items-center gap-3 rounded-xl bg-white p-4 shadow-sm">
        <div role="group" className="flex gap-2">
          {(["true", "false"] as const).map((value) => (
            <button
              key={value}
              type="button"
              aria-pressed={mine === value}
              onClick={() => set("mine", value)}
              className={`min-h-12 rounded-lg px-4 text-lg font-semibold ${mine === value ? "bg-gray-900 text-white" : "border border-gray-300"}`}
            >
              {value === "true" ? t("maint.mine") : t("maint.all")}
            </button>
          ))}
        </div>
        <label className="flex items-center gap-2 text-lg">
          {t("maint.status")}
          <select value={query.status} onChange={(e) => set("status", e.target.value)} className={select}>
            <option value="open">{t("maint.open")}</option>
            <option value="">{t("maint.allStatuses")}</option>
            {ACTION_STATUSES.map((s) => (
              <option key={s} value={s}>
                {statusLabel(s)}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-2 text-lg">
          {t("maint.priority")}
          <select value={query.priority} onChange={(e) => set("priority", e.target.value)} className={select}>
            <option value="">{t("maint.allStatuses")}</option>
            {PRIORITIES.map((p) => (
              <option key={p} value={p}>
                {priorityLabel(p)}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-2 text-lg">
          {t("alerts.line")}
          <select value={query.line} onChange={(e) => set("line", e.target.value)} className={select}>
            <option value="">{t("maint.allStatuses")}</option>
            {(lines.data ?? []).map((line) => (
              <option key={line.id} value={line.id}>
                {line.name}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-2 text-lg">
          <input type="checkbox" checked={query.overdue === "true"} onChange={(e) => set("overdue", e.target.checked ? "true" : "")} className="h-6 w-6" />
          {t("maint.overdueOnly")}
        </label>
        <button type="button" onClick={() => void exportCsv()} className="ml-auto inline-flex min-h-12 items-center gap-2 rounded-lg border-2 border-gray-400 px-4 text-lg">
          <Download aria-hidden className="h-5 w-5" />
          {t("maint.export")}
        </button>
        {exportError && <p role="alert" className="text-lg text-red-700">{t("table.exportFailed")}</p>}
      </section>
      <Panel isLoading={actions.isLoading} isError={actions.isError} isEmpty={actions.data?.results.length === 0} emptyText={t("maint.empty")}>
        <ul className="flex flex-col gap-3">
          {(actions.data?.results ?? []).map((action) => (
            <ActionRow key={action.id} action={action} />
          ))}
        </ul>
      </Panel>
    </main>
  );
}
