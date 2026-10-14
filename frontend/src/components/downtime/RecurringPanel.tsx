import type { RecurringResponse } from "../../api/analysisTypes.ts";
import { t } from "../../i18n/t.ts";
import { formatDateTime, formatDuration } from "../../lib/time.ts";

export function RecurringPanel({ recurring, zone }: { recurring: RecurringResponse; zone: string }) {
  return (
    <section className="rounded-xl bg-white p-4 shadow-sm">
      <h2 className="text-xl font-semibold">{t("recurring.title")}</h2>
      {recurring.threshold !== null && (
        <p className="mb-2 text-base text-gray-600">
          {t("recurring.threshold", { threshold: recurring.threshold })}
        </p>
      )}
      {recurring.items.length === 0 ? (
        <p className="text-lg text-gray-600">{t("recurring.empty")}</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {recurring.items.map((item) => (
            <li
              key={`${item.machine.id}-${item.reason?.id ?? item.alarm_code ?? "none"}`}
              className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-lg"
            >
              <p className="font-semibold">
                {item.machine.name} ·{" "}
                {item.reason ? item.reason.name : item.alarm_code ?? t("recurring.noAlarm")}
              </p>
              <p className="text-gray-700">
                {t("recurring.item", {
                  count: item.count,
                  duration: formatDuration(item.total_seconds),
                  time: formatDateTime(item.last_occurrence, zone),
                })}
              </p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
