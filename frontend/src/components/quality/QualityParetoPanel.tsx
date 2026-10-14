import {
  Bar,
  CartesianGrid,
  Cell,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { QualityGroupBy, QualityPareto, QualityParetoGroup } from "../../api/qualityTypes.ts";
import type { MessageKey } from "../../i18n/en.ts";
import { t } from "../../i18n/t.ts";

const GROUPS: { key: QualityGroupBy; label: MessageKey }[] = [
  { key: "defect_type", label: "qpareto.byType" },
  { key: "station", label: "qpareto.byStation" },
  { key: "machine", label: "qpareto.byMachine" },
  { key: "product", label: "qpareto.byProduct" },
];

interface QualityParetoPanelProps {
  pareto: QualityPareto;
  groupBy: QualityGroupBy;
  onGroupBy: (group: QualityGroupBy) => void;
  onSelectGroup: (group: QualityParetoGroup) => void;
  selectedKey: string | null;
}

/** Bars: defects per group; line: cumulative %; dashed line at 80 %. False rejects excluded. */
export function QualityParetoPanel({ pareto, groupBy, onGroupBy, onSelectGroup, selectedKey }: QualityParetoPanelProps) {
  const rows = pareto.groups.map((g) => ({
    key: g.key,
    label: g.label,
    count: g.count,
    cumulative: Math.round((g.cumulative_share ?? 0) * 1000) / 10,
  }));
  const select = (key: string) => {
    const group = pareto.groups.find((g) => g.key === key);
    if (group) onSelectGroup(group);
  };

  return (
    <section aria-labelledby="qpareto-title">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-3">
        <h2 id="qpareto-title" className="text-xl font-semibold">
          {t("qpareto.title")}
        </h2>
        <div className="flex flex-wrap gap-2" role="group" aria-label={t("qpareto.groupBy")}>
          {GROUPS.map((g) => (
            <button
              key={g.key}
              type="button"
              aria-pressed={groupBy === g.key}
              onClick={() => onGroupBy(g.key)}
              data-testid={`qpareto-group-${g.key}`}
              className={`min-h-11 rounded-lg px-3 text-lg ${
                groupBy === g.key ? "bg-gray-900 text-white" : "border border-gray-300"
              }`}
            >
              {t(g.label)}
            </button>
          ))}
        </div>
      </div>
      {pareto.false_rejects_excluded > 0 && (
        <p className="mb-2 text-base text-gray-600">
          {t("qpareto.excluded", { count: pareto.false_rejects_excluded })}
        </p>
      )}

      {rows.length === 0 ? (
        <p className="text-lg text-gray-600">{t("qpareto.empty")}</p>
      ) : (
        <>
          <div className="h-72 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={rows} margin={{ top: 8, right: 16, bottom: 40, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="label" interval={0} angle={-20} textAnchor="end" tick={{ fontSize: 13 }} />
                <YAxis yAxisId="left" allowDecimals={false} tick={{ fontSize: 13 }} />
                <YAxis yAxisId="right" orientation="right" domain={[0, 100]} unit="%" tick={{ fontSize: 13 }} />
                <Tooltip />
                <ReferenceLine yAxisId="right" y={80} stroke="#b45309" strokeDasharray="6 4" />
                <Bar
                  yAxisId="left"
                  dataKey="count"
                  name={t("qpareto.count")}
                  cursor="pointer"
                  onClick={(entry) => {
                    const key = (entry as { payload?: { key?: string } }).payload?.key;
                    if (key) select(key);
                  }}
                >
                  {rows.map((row) => (
                    <Cell key={row.key} fill={row.key === selectedKey ? "#7c2d12" : "#ea580c"} />
                  ))}
                </Bar>
                <Line yAxisId="right" dataKey="cumulative" name={t("qpareto.cumulative")} stroke="#1e3a8a" strokeWidth={2} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
          {/* The same data as buttons: readable, keyboard- and touch-friendly. */}
          <p className="mt-2 text-base text-gray-600">{t("qpareto.filterHint")}</p>
          <ul className="mt-1 flex flex-wrap gap-2">
            {pareto.groups.map((g) => (
              <li key={g.key}>
                <button
                  type="button"
                  aria-pressed={selectedKey === g.key}
                  onClick={() => onSelectGroup(g)}
                  data-testid={`qpareto-bar-${g.key}`}
                  className={`min-h-11 rounded-lg border px-3 text-left text-base ${
                    selectedKey === g.key ? "border-orange-800 bg-orange-50 font-semibold" : "border-gray-300"
                  }`}
                >
                  {t("qpareto.row", {
                    label: g.label,
                    count: g.count,
                    share: Math.round((g.share ?? 0) * 1000) / 10,
                  })}
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
