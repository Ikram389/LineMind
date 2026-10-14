import type { SummaryResponse } from "../../api/analysisTypes.ts";
import { t } from "../../i18n/t.ts";
import { formatDuration } from "../../lib/time.ts";

function Card({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-xl bg-white p-4 shadow-sm">
      <p className="text-lg text-gray-600">{label}</p>
      <p className="text-4xl font-extrabold tabular-nums text-gray-900">{value}</p>
      {sub && <p className="text-base text-gray-600">{sub}</p>}
    </div>
  );
}

export function SummaryCards({ summary }: { summary: SummaryResponse }) {
  return (
    <div className="flex flex-col gap-2">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Card
          label={t("summary.total")}
          value={formatDuration(summary.total_seconds)}
          sub={t("summary.lostUnits", { units: summary.estimated_lost_units.units.toLocaleString("en-GB") })}
        />
        <Card label={t("summary.stops")} value={String(summary.stops)} />
        <Card label={t("summary.unclassified")} value={String(summary.unclassified)} />
        <Card
          label={t("summary.longest")}
          value={summary.longest ? formatDuration(summary.longest.duration_seconds) : t("summary.none")}
          sub={summary.longest ? summary.longest.machine.name : undefined}
        />
      </div>
      {summary.secondary_breakdowns > 0 && (
        <p className="rounded-lg bg-amber-50 p-2 text-lg text-amber-900">
          {t("summary.secondary", { count: summary.secondary_breakdowns })}
        </p>
      )}
    </div>
  );
}
