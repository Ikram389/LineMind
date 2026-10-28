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

import { useChartTheme } from "../../lib/chartTheme.ts";

const MAX_TICK = 18;
/** Long group names are shortened under the bars; the full name is in the tooltip and the list. */
const shorten = (label: string) => (label.length > MAX_TICK ? `${label.slice(0, MAX_TICK - 1)}…` : label);

export interface ParetoRow {
  key: string;
  label: string;
  value: number;
  /** Cumulative share, 0–100. */
  cumulative: number;
}

interface ParetoChartProps {
  rows: ParetoRow[];
  /** e.g. "Downtime (min)" or "Defects". */
  valueLabel: string;
  cumulativeLabel: string;
  ariaLabel: string;
  selectedKey?: string | null;
  onSelect?: (key: string) => void;
}

/** Bars per group (largest first), the cumulative % line and a dashed 80 % reference.
 *  Colours come from the theme tokens. Always shown next to the same data as buttons or a
 *  list, so it is never the only way to read or filter. */
export function ParetoChart({ rows, valueLabel, cumulativeLabel, ariaLabel, selectedKey, onSelect }: ParetoChartProps) {
  const theme = useChartTheme();
  const tick = { fontSize: theme.tick, fill: theme.muted };
  return (
    <div className="h-72 w-full" role="img" aria-label={ariaLabel}>
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={rows} margin={{ top: 8, right: 8, bottom: 48, left: 0 }}>
          <CartesianGrid stroke={theme.grid} vertical={false} />
          <XAxis dataKey="label" interval={0} angle={-20} textAnchor="end" tick={tick} stroke={theme.grid} tickFormatter={shorten} />
          <YAxis yAxisId="value" tick={tick} stroke={theme.grid} width={theme.tick * 4} />
          <YAxis yAxisId="cumulative" orientation="right" domain={[0, 100]} unit="%" tick={tick} stroke={theme.grid} width={theme.tick * 4} />
          <Tooltip
            cursor={{ fill: theme.grid, opacity: 0.4 }}
            contentStyle={{ background: theme.surface, borderColor: theme.grid, color: theme.ink, borderRadius: 8 }}
          />
          <ReferenceLine yAxisId="cumulative" y={80} stroke={theme.blocked} strokeDasharray="6 4" />
          <Bar
            yAxisId="value"
            dataKey="value"
            name={valueLabel}
            radius={[4, 4, 0, 0]}
            maxBarSize={56}
            cursor={onSelect ? "pointer" : undefined}
            onClick={(entry) => {
              const key = (entry as { payload?: { key?: string } }).payload?.key;
              if (key && onSelect) onSelect(key);
            }}
          >
            {rows.map((row) => (
              <Cell
                key={row.key}
                fill={theme.accent}
                fillOpacity={selectedKey && row.key !== selectedKey ? 0.35 : 1}
              />
            ))}
          </Bar>
          <Line yAxisId="cumulative" dataKey="cumulative" name={cumulativeLabel} stroke={theme.blocked} strokeWidth={2} dot={{ r: 3 }} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
