import { Repeat } from "lucide-react";

import type { RecurringResponse } from "../../api/analysisTypes.ts";
import { t } from "../../i18n/t.ts";
import { formatDateTime, formatDuration } from "../../lib/time.ts";
import { CreateActionButton } from "../maintenance/CreateActionDialog.tsx";
import { Card } from "../ui/Card.tsx";
import { EmptyState } from "../ui/Feedback.tsx";

export function RecurringPanel({
  recurring,
  zone,
  range,
}: {
  recurring: RecurringResponse;
  zone: string;
  /** The analysed range, so "Create action" links the stops of that range. */
  range?: { start: string; end: string };
}) {
  return (
    <Card title={t("recurring.title")}>
      {recurring.threshold !== null && (
        <p className="mb-3 text-small text-ink-muted">{t("recurring.threshold", { threshold: recurring.threshold })}</p>
      )}
      {recurring.items.length === 0 ? (
        <EmptyState icon={Repeat} title={t("recurring.empty")} />
      ) : (
        <ul className="flex flex-col divide-y divide-line">
          {recurring.items.map((item) => (
            <li
              key={`${item.machine.id}-${item.reason?.id ?? item.alarm_code ?? "none"}`}
              className="flex flex-col gap-2 py-3 first:pt-0 last:pb-0"
            >
              <p className="flex items-start gap-2 text-body font-semibold text-ink">
                <Repeat aria-hidden className="mt-1 h-4 w-4 shrink-0 text-warning" />
                <span>
                  {item.machine.name} · {item.reason ? item.reason.name : item.alarm_code ?? t("recurring.noAlarm")}
                </span>
              </p>
              <p className="text-small text-ink-muted">
                {t("recurring.item", {
                  count: item.count,
                  duration: formatDuration(item.total_seconds),
                  time: formatDateTime(item.last_occurrence, zone),
                })}
              </p>
              {range && (
                <div>
                  <CreateActionButton
                    compact
                    source={{
                      source: "recurring",
                      machine: item.machine.id,
                      ...(item.reason ? { reason: item.reason.id } : { alarm: item.alarm_code ?? "" }),
                      start: range.start,
                      end: range.end,
                    }}
                  />
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
