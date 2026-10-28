import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "../../lib/cn.ts";

const TONES = {
  neutral: "border-line-strong bg-surface-muted text-ink",
  accent: "border-accent bg-accent-soft text-accent",
  warning: "border-warning bg-warning-soft text-warning",
  critical: "border-critical bg-critical-soft text-critical",
} as const;

interface TagProps {
  children: ReactNode;
  tone?: keyof typeof TONES;
  icon?: LucideIcon;
  className?: string;
  "data-testid"?: string;
}

/** A small label for text without its own meaning colour (a view, a code, "Consequence").
 *  States and severities use StatusBadge instead. A tone is never the only signal: the
 *  text always says it. */
export function Tag({ children, tone = "neutral", icon: Icon, className, ...rest }: TagProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-small font-semibold",
        TONES[tone],
        className,
      )}
      {...rest}
    >
      {Icon && <Icon aria-hidden className="h-3.5 w-3.5 shrink-0" />}
      {children}
    </span>
  );
}
