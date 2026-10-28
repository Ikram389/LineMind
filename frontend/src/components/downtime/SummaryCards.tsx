import type { SummaryResponse } from "../../api/analysisTypes.ts";
import { t } from "../../i18n/t.ts";
import { formatDuration } from "../../lib/time.ts";
import { InlineNotice } from "../ui/Feedback.tsx";
import { StatCard } from "../ui/StatCard.tsx";

export function SummaryCards({ summary }: { summary: SummaryResponse }) {
  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard
          label={t("summary.total")}
          value={formatDuration(summary.total_seconds)}
          sub={t("summary.lostUnits", { units: summary.estimated_lost_units.units.toLocaleString("en-GB") })}
        />
        <StatCard label={t("summary.stops")} value={String(summary.stops)} />
        <StatCard label={t("summary.unclassified")} value={String(summary.unclassified)} />
        <StatCard
          label={t("summary.longest")}
          value={summary.longest ? formatDuration(summary.longest.duration_seconds) : t("summary.none")}
          sub={summary.longest ? summary.longest.machine.name : undefined}
        />
      </div>
      {summary.secondary_breakdowns > 0 && (
        <InlineNotice tone="warning">{t("summary.secondary", { count: summary.secondary_breakdowns })}</InlineNotice>
      )}
    </div>
  );
}
