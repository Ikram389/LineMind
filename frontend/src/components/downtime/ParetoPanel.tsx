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

import type { ParetoGroupBy, ParetoResponse } from "../../api/analysisTypes.ts";
import type { MessageKey } from "../../i18n/en.ts";
import { t } from "../../i18n/t.ts";
import { formatDuration } from "../../lib/time.ts";

const GROUPS: { key: ParetoGroupBy; label: MessageKey }[] = [
  { key: "reason", label: "pareto.byReason" },
  { key: "machine", label: "pareto.byMachine" },
  { key: "category", label: "pareto.byCategory" },
  { key: "alarm_code", label: "pareto.byAlarm" },
];

interface ParetoPanelProps {
  pareto: ParetoResponse;
  groupBy: ParetoGroupBy;
  onGroupBy: (group: ParetoGroupBy) => void;
  onSelectGroup: (key: string) => void;
  selectedKey: string | null;
}

/** Bars: downtime per group; line: cumulative %; dashed line at 80 %. */
export function ParetoPanel({ pareto, groupBy, onGroupBy, onSelectGroup, selectedKey }: ParetoPanelProps) {
  const rows = pareto.groups.map((g) => ({
    key: g.key,
    label: g.label,
    minutes: Math.round((g.total_seconds / 60) * 10) / 10,
    cumulative: Math.round(g.cumulative_share * 1000) / 10,
  }));

  return (
    <section className="rounded-xl bg-white p-4 shadow-sm" aria-labelledby="pareto-title">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-3">
        <h2 id="pareto-title" className="text-xl font-semibold">
          {t("pareto.title")}{" "}
          <span
            data-testid="pareto-view"
            className={`ml-2 rounded px-2 py-1 text-base font-bold ${
              pareto.view === "line" ? "bg-blue-100 text-blue-900" : "bg-purple-100 text-purple-900"
            }`}
          >
            {t(pareto.view === "line" ? "pareto.lineView" : "pareto.machineView")}
          </span>
        </h2>
        <div className="flex flex-wrap gap-2" role="group" aria-label={t("pareto.groupBy")}>
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
      <p className="mb-3 text-base text-gray-600">{pareto.view_note}</p>

      {rows.length === 0 ? (
        <p className="text-lg text-gray-600">{t("pareto.empty")}</p>
      ) : (
        <>
          <div className="h-72 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={rows} margin={{ top: 8, right: 16, bottom: 40, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="label" interval={0} angle={-20} textAnchor="end" tick={{ fontSize: 13 }} />
                <YAxis yAxisId="left" tick={{ fontSize: 13 }} label={{ value: t("pareto.duration"), angle: -90, position: "insideLeft" }} />
                <YAxis yAxisId="right" orientation="right" domain={[0, 100]} unit="%" tick={{ fontSize: 13 }} />
                <Tooltip />
                <ReferenceLine yAxisId="right" y={80} stroke="#b45309" strokeDasharray="6 4" />
                <Bar
                  yAxisId="left"
                  dataKey="minutes"
                  name={t("pareto.duration")}
                  cursor="pointer"
                  onClick={(entry) => {
                    const key = (entry as { payload?: { key?: string } }).payload?.key;
                    if (key) onSelectGroup(key);
                  }}
                >
                  {rows.map((row) => (
                    <Cell key={row.key} fill={row.key === selectedKey ? "#1e3a8a" : "#3b82f6"} />
                  ))}
                </Bar>
                <Line yAxisId="right" dataKey="cumulative" name={t("pareto.cumulative")} stroke="#b45309" strokeWidth={2} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
          {/* The same data as buttons: readable, keyboard- and touch-friendly. */}
          <p className="mt-2 text-base text-gray-600">{t("pareto.filterHint")}</p>
          <ul className="mt-1 flex flex-wrap gap-2">
            {pareto.groups.map((g) => (
              <li key={g.key}>
                <button
                  type="button"
                  aria-pressed={selectedKey === g.key}
                  onClick={() => onSelectGroup(g.key)}
                  data-testid={`pareto-group-${g.key}`}
                  className={`min-h-11 rounded-lg border px-3 text-left text-base ${
                    selectedKey === g.key ? "border-blue-800 bg-blue-50 font-semibold" : "border-gray-300"
                  }`}
                >
                  {t("pareto.row", {
                    label: g.label,
                    duration: formatDuration(g.total_seconds),
                    count: g.occurrences,
                    share: (g.share * 100).toFixed(1),
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
