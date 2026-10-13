import type { DowntimeEvent } from "../api/types.ts";
import { t } from "../i18n/t.ts";
import { formatDateTime, formatDuration } from "../lib/time.ts";

const CATEGORY_KEY = {
  breakdown: "category.breakdown",
  blocked: "category.blocked",
  starved: "category.starved",
  planned: "category.planned",
  no_data: "category.no_data",
} as const;

/** Read-only list of a machine's downtime (classification UI comes in build step 8). */
export function DowntimeTable({ events, zone }: { events: DowntimeEvent[]; zone: string }) {
  const newestFirst = [...events].sort(
    (a, b) => Date.parse(b.started_at) - Date.parse(a.started_at),
  );
  return (
    <table className="w-full text-left text-lg">
      <thead className="border-b border-gray-300 text-gray-600">
        <tr>
          <th className="py-2 pr-4">{t("detail.colStart")}</th>
          <th className="py-2 pr-4">{t("detail.colDuration")}</th>
          <th className="py-2 pr-4">{t("detail.colCategory")}</th>
          <th className="py-2">{t("detail.colClassification")}</th>
        </tr>
      </thead>
      <tbody>
        {newestFirst.map((event) => (
          <tr key={event.id} className="border-b border-gray-100 align-top">
            <td className="py-2 pr-4 tabular-nums">{formatDateTime(event.started_at, zone)}</td>
            <td className="py-2 pr-4 tabular-nums">
              {formatDuration(event.duration_seconds)}
              {event.is_ongoing && <span className="ml-2 text-red-700">({t("detail.ongoing")})</span>}
            </td>
            <td className="py-2 pr-4">
              {t(CATEGORY_KEY[event.category])}
              {event.alarm_code && <span className="ml-2 text-gray-600">{event.alarm_code}</span>}
              {event.is_first_stop && (
                <span className="ml-2 rounded bg-red-800 px-2 py-0.5 text-sm font-bold uppercase text-white">
                  {t("machine.firstStop")}
                </span>
              )}
            </td>
            <td className="py-2">
              {event.classification ? event.classification.reason.name : (
                <span className="text-gray-500">{t("detail.notClassified")}</span>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
