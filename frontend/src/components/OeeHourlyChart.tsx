import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { OeeBucket } from "../api/types.ts";
import { t } from "../i18n/t.ts";
import { useChartTheme } from "../lib/chartTheme.ts";
import { formatTime } from "../lib/time.ts";

interface Row {
  hour: string;
  oee: number | null;
  availability: number | null;
  performance: number | null;
  quality: number | null;
}

export function OeeHourlyChart({ buckets, zone }: { buckets: OeeBucket[]; zone: string }) {
  const theme = useChartTheme();
  const rows: Row[] = buckets.map((b) => ({
    hour: formatTime(b.start, zone),
    oee: b.oee.percent,
    availability: b.availability.percent,
    performance: b.performance.percent,
    quality: b.quality.percent,
  }));
  const tick = { fontSize: theme.tick, fill: theme.muted };
  return (
    <div className="h-64 w-full" role="img" aria-label={t("oee.chartLabel")}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows} margin={{ top: 8, right: 8, bottom: 8, left: 0 }}>
          <CartesianGrid stroke={theme.grid} vertical={false} />
          <XAxis dataKey="hour" tick={tick} stroke={theme.grid} />
          <YAxis domain={[0, 100]} unit="%" tick={tick} stroke={theme.grid} width={theme.tick * 4} />
          <Tooltip
            cursor={{ fill: theme.grid, opacity: 0.4 }}
            contentStyle={{ background: theme.surface, borderColor: theme.grid, color: theme.ink, borderRadius: 8 }}
            formatter={(value, name) => [value === null ? "—" : `${String(value)}%`, String(name)]}
          />
          <Bar dataKey="oee" name="OEE" fill={theme.accent} radius={[4, 4, 0, 0]} maxBarSize={48} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
