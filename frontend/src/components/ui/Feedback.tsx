/** Empty, loading and notice states: every panel shows one of these instead of a blank. */
import { CircleAlert, Info, type LucideIcon, OctagonAlert, TriangleAlert } from "lucide-react";
import type { ReactNode } from "react";

import { t } from "../../i18n/t.ts";
import { cn } from "../../lib/cn.ts";

interface EmptyStateProps {
  title: ReactNode;
  /** One short, helpful sentence: why it is empty or what to do. */
  text?: ReactNode;
  icon?: LucideIcon;
  action?: ReactNode;
}

export function EmptyState({ title, text, icon: Icon = Info, action }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center gap-2 px-4 py-6 text-center">
      <Icon aria-hidden className="h-8 w-8 text-ink-muted" />
      <p className="max-w-prose text-body font-semibold text-ink">{title}</p>
      {text && <p className="max-w-prose text-body text-ink-muted">{text}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

/** Grey blocks where content will appear (announced as loading to screen readers). */
export function Skeleton({ lines = 3, className }: { lines?: number; className?: string }) {
  return (
    <div role="status" aria-live="polite" className={cn("flex flex-col gap-3", className)}>
      <span className="sr-only">{t("panel.loading")}</span>
      {Array.from({ length: lines }, (_, i) => (
        <div
          key={i}
          aria-hidden
          className={cn("h-5 animate-pulse rounded-control bg-surface-muted", i === lines - 1 && lines > 1 && "w-2/3")}
        />
      ))}
    </div>
  );
}

export function ErrorState({ text }: { text?: ReactNode }) {
  return (
    <p role="alert" className="flex items-center gap-2 text-body font-semibold text-critical">
      <OctagonAlert aria-hidden className="h-5 w-5 shrink-0" />
      {text ?? t("panel.error")}
    </p>
  );
}

const NOTICE: Record<"info" | "warning" | "critical", { Icon: LucideIcon; tone: string }> = {
  info: { Icon: Info, tone: "bg-info-soft text-info" },
  warning: { Icon: TriangleAlert, tone: "bg-warning-soft text-warning" },
  critical: { Icon: CircleAlert, tone: "bg-critical-soft text-critical" },
};

/** A compact message inside a card (e.g. the OEE notes). */
export function InlineNotice({ tone = "info", children }: { tone?: keyof typeof NOTICE; children: ReactNode }) {
  const { Icon, tone: classes } = NOTICE[tone];
  return (
    <p className={cn("flex items-start gap-2 rounded-control px-3 py-2 text-small font-semibold", classes)}>
      <Icon aria-hidden className="mt-0.5 h-4 w-4 shrink-0" />
      <span>{children}</span>
    </p>
  );
}
