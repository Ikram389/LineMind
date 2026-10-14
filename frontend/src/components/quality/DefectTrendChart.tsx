import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import type { QualityTrend, TrendGroupBy } from "../../api/qualityTypes.ts";
import type { MessageKey } from "../../i18n/en.ts";
import { t } from "../../i18n/t.ts";
import { formatCount, formatRate } from "../../lib/qualityFormat.ts";

const GROUPS: { key: TrendGroupBy; label: MessageKey }[] = [
  { key: "hour", label: "qtrend.hour" },
  { key: "shift", label: "qtrend.shift" },
  { key: "day", label: "qtrend.day" },
];

interface DefectTrendChartProps {
  trend: QualityTrend;
  groupBy: TrendGroupBy;
  onGroupBy: (group: TrendGroupBy) => void;
}

/** Defect rate per bucket; the whole-range rate comes from summed counts (backend). */
export function DefectTrendChart({ trend, groupBy, onGroupBy }: DefectTrendChartProps) {
  const rows = trend.buckets.map((b) => ({
    label: b.label,
    rate: b.defect_rate === null ? null : Math.round(b.defect_rate * 10000) / 100,
  }));

  return (
    <section aria-labelledby="qtrend-title">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-3">
        <h2 id="qtrend-title" className="text-xl font-semibold">
          {t("qtrend.title")}
        </h2>
        <div className="flex flex-wrap gap-2" role="group" aria-label={t("qtrend.groupBy")}>
          {GROUPS.map((g) => (
            <button
              key={g.key}
              type="button"
              aria-pressed={groupBy === g.key}
              onClick={() => onGroupBy(g.key)}
              className={`min-h-11 rounded-lg px-3 text-lg ${
                groupBy === g.key ? "bg-gray-900 text-white" : "border border-gray-300"
              }`}
            >
              {t(g.label)}
            </button>
          ))}
        </div>
      </div>
      <p className="mb-2 text-lg" data-testid="qtrend-total">
        {t("qtrend.total", {
          rate: formatRate(trend.total.defect_rate),
          defects: formatCount(trend.total.defects),
          total: formatCount(trend.total.total_count),
        })}
      </p>
      {trend.total.total_count === 0 ? (
        <p className="text-lg text-gray-600">{t("qtrend.empty")}</p>
      ) : (
        <div className="h-64 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={rows} margin={{ top: 8, right: 16, bottom: 24, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="label" tick={{ fontSize: 13 }} />
              <YAxis unit="%" tick={{ fontSize: 13 }} />
              <Tooltip />
              <Line dataKey="rate" name={t("qtrend.rate")} stroke="#ea580c" strokeWidth={2} connectNulls={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </section>
  );
}
