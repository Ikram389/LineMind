import { ArrowDownUp } from "lucide-react";

import type { AnalysedDowntimeEvent } from "../../api/analysisTypes.ts";
import type { MessageKey } from "../../i18n/en.ts";
import { t } from "../../i18n/t.ts";
import type { Permissions } from "../../lib/permissions.ts";
import { formatDateTime, formatDuration } from "../../lib/time.ts";

const CATEGORY_KEY: Record<string, MessageKey> = {
  breakdown: "category.breakdown",
  blocked: "category.blocked",
  starved: "category.starved",
  planned: "category.planned",
  no_data: "category.no_data",
};

const ROLE_STYLE: Record<string, string> = {
  first_observed_stop: "bg-red-800 text-white",
  secondary_breakdown: "bg-orange-600 text-white",
  consequence: "bg-gray-200 text-gray-800",
};

interface DowntimeEventsTableProps {
  events: AnalysedDowntimeEvent[];
  total: number;
  offset: number;
  limit: number;
  zone: string;
  ordering: string;
  permissions: Permissions;
  selected: Set<number>;
  onToggle: (id: number) => void;
  onToggleAll: (ids: number[]) => void;
  onSort: (ordering: string) => void;
  onPage: (offset: number) => void;
  onClassify: (event: AnalysedDowntimeEvent) => void;
  onOpenIncident: (incidentId: number) => void;
}

export function DowntimeEventsTable({
  events,
  total,
  offset,
  limit,
  zone,
  ordering,
  permissions,
  selected,
  onToggle,
  onToggleAll,
  onSort,
  onPage,
  onClassify,
  onOpenIncident,
}: DowntimeEventsTableProps) {
  if (events.length === 0) return <p className="text-lg text-gray-600">{t("table.empty")}</p>;

  const sortButton = (field: string, label: MessageKey) => {
    const next = ordering === field ? `-${field}` : field;
    return (
      <button
        type="button"
        onClick={() => onSort(next)}
        aria-label={t("table.sortBy", { column: t(label) })}
        className="inline-flex items-center gap-1 font-semibold"
      >
        {t(label)}
        <ArrowDownUp aria-hidden className="h-4 w-4" />
      </button>
    );
  };

  return (
    <div>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-lg">
          <thead className="border-b-2 border-gray-300 text-gray-700">
            <tr>
              {permissions.canBulkClassify && (
                <th className="p-2">
                  <input
                    type="checkbox"
                    aria-label={t("table.selectAll")}
                    checked={events.every((e) => selected.has(e.id))}
                    onChange={() => onToggleAll(events.map((e) => e.id))}
                    className="h-6 w-6"
                  />
                </th>
              )}
              <th className="p-2">{sortButton("started_at", "table.start")}</th>
              <th className="p-2">{sortButton("machine", "table.machine")}</th>
              <th className="p-2">{sortButton("duration", "table.duration")}</th>
              <th className="p-2">{t("table.category")}</th>
              <th className="p-2">{t("table.reason")}</th>
              <th className="p-2">{t("table.classifiedBy")}</th>
              <th className="p-2">{t("table.role")}</th>
              <th className="p-2">{t("table.incident")}</th>
              {permissions.canClassify && <th className="p-2" />}
            </tr>
          </thead>
          <tbody>
            {events.map((event) => (
              <tr key={event.id} className="border-b border-gray-100 align-middle" data-testid={`event-row-${event.id}`}>
                {permissions.canBulkClassify && (
                  <td className="p-2">
                    <input
                      type="checkbox"
                      aria-label={t("table.select", {
                        machine: event.machine.name,
                        time: formatDateTime(event.started_at, zone),
                      })}
                      checked={selected.has(event.id)}
                      onChange={() => onToggle(event.id)}
                      className="h-6 w-6"
                    />
                  </td>
                )}
                <td className="p-2 tabular-nums">{formatDateTime(event.started_at, zone)}</td>
                <td className="p-2">{event.machine.name}</td>
                <td className="p-2 tabular-nums">
                  {formatDuration(event.clipped_duration_seconds ?? event.duration_seconds)}
                  {event.is_ongoing && <span className="ml-1 text-red-700">({t("detail.ongoing")})</span>}
                </td>
                <td className="p-2">
                  {t(CATEGORY_KEY[event.category] ?? "category.breakdown")}
                  {event.alarm_code && <span className="ml-1 text-gray-600">{event.alarm_code}</span>}
                </td>
                <td className="p-2">
                  {event.classification?.reason.name ?? (
                    <span className="text-gray-500">{t("detail.notClassified")}</span>
                  )}
                </td>
                <td className="p-2 text-base text-gray-700">{event.classification?.created_by ?? ""}</td>
                <td className="p-2">
                  {event.role_in_incident && (
                    <span className={`rounded px-2 py-0.5 text-sm font-bold ${ROLE_STYLE[event.role_in_incident] ?? ""}`}>
                      {t(`role.${event.role_in_incident}` as MessageKey)}
                    </span>
                  )}
                </td>
                <td className="p-2">
                  {event.incident !== null && (
                    <button
                      type="button"
                      onClick={() => onOpenIncident(event.incident as number)}
                      className="min-h-11 px-2 text-blue-800 underline"
                    >
                      #{event.incident}
                    </button>
                  )}
                </td>
                {permissions.canClassify && (
                  <td className="p-2">
                    <button
                      type="button"
                      onClick={() => onClassify(event)}
                      className="min-h-12 rounded-lg bg-blue-700 px-4 text-lg font-semibold text-white"
                    >
                      {event.classification ? t("table.reclassify") : t("table.classify")}
                    </button>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-3 flex items-center justify-between text-lg">
        <span>{t("table.page", { from: offset + 1, to: Math.min(offset + limit, total), total })}</span>
        <div className="flex gap-2">
          <button
            type="button"
            disabled={offset === 0}
            onClick={() => onPage(Math.max(0, offset - limit))}
            className="min-h-12 rounded-lg border border-gray-300 px-4 disabled:opacity-40"
          >
            {t("table.previous")}
          </button>
          <button
            type="button"
            disabled={offset + limit >= total}
            onClick={() => onPage(offset + limit)}
            className="min-h-12 rounded-lg border border-gray-300 px-4 disabled:opacity-40"
          >
            {t("table.next")}
          </button>
        </div>
      </div>
    </div>
  );
}
