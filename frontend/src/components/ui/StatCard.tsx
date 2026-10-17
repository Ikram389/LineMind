import { TrendingDown, TrendingUp } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "../../lib/cn.ts";

interface StatCardProps {
  label: ReactNode;
  value: ReactNode;
  sub?: ReactNode;
  /** Optional trend; "good" decides the colour (lower can be better, e.g. defects). */
  trend?: { direction: "up" | "down"; good: boolean; text: ReactNode };
  size?: "md" | "lg";
  "data-testid"?: string;
}

/** A big number with its label. Figures use tabular numbers. */
export function StatCard({ label, value, sub, trend, size = "md", ...rest }: StatCardProps) {
  const Arrow = trend?.direction === "down" ? TrendingDown : TrendingUp;
  return (
    <div className="rounded-card border border-line bg-surface p-4" {...rest}>
      <p className="text-small font-semibold text-ink-muted">{label}</p>
      <p className={cn("mt-1 font-bold tabular-nums text-ink", size === "lg" ? "text-hero" : "text-stat")}>{value}</p>
      {sub && <p className="mt-1 text-small text-ink-muted">{sub}</p>}
      {trend && (
        <p className={cn("mt-1 inline-flex items-center gap-1 text-small font-semibold", trend.good ? "text-improved" : "text-worse")}>
          <Arrow aria-hidden className="h-4 w-4" />
          {trend.text}
        </p>
      )}
    </div>
  );
}
