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
import { formatTime } from "../lib/time.ts";

interface Row {
  hour: string;
  oee: number | null;
  availability: number | null;
  performance: number | null;
  quality: number | null;
}

export function OeeHourlyChart({ buckets, zone }: { buckets: OeeBucket[]; zone: string }) {
  const rows: Row[] = buckets.map((b) => ({
    hour: formatTime(b.start, zone),
    oee: b.oee.percent,
    availability: b.availability.percent,
    performance: b.performance.percent,
    quality: b.quality.percent,
  }));
  return (
    <div className="h-64 w-full" aria-label="Hourly OEE chart">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows} margin={{ top: 8, right: 8, bottom: 8, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="hour" tick={{ fontSize: 16 }} />
          <YAxis domain={[0, 100]} unit="%" tick={{ fontSize: 14 }} width={56} />
          <Tooltip
            formatter={(value, name) => [value === null ? "—" : `${String(value)}%`, String(name)]}
          />
          <Bar dataKey="oee" name="OEE" fill="#1d4ed8" radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
