import { t } from "../../i18n/t.ts";
import { cn } from "../../lib/cn.ts";
import { STATUS, type StatusKind } from "./status.ts";

const SIZES = {
  sm: "gap-1 px-2 py-0.5 text-small",
  md: "gap-1.5 px-2.5 py-1 text-body",
  lg: "gap-2 px-3 py-1.5 text-title",
  hero: "gap-3 px-4 py-2 text-hero",
} as const;
const ICON_SIZES = { sm: "h-4 w-4", md: "h-5 w-5", lg: "h-6 w-6", hero: "h-12 w-12" } as const;

interface StatusBadgeProps {
  kind: StatusKind;
  size?: keyof typeof SIZES;
  /** Replaces the default text (e.g. "Reclassified as Q03"); the icon stays. */
  label?: string;
  className?: string;
}

/** A state or severity: colour + icon + written text, always together. */
export function StatusBadge({ kind, size = "md", label, className }: StatusBadgeProps) {
  const style = STATUS[kind];
  return (
    <span
      data-status={kind}
      className={cn("inline-flex items-center rounded-control font-bold", style.tone, SIZES[size], className)}
    >
      <style.Icon aria-hidden className={cn("shrink-0", ICON_SIZES[size])} />
      <span>{label ?? t(style.label)}</span>
    </span>
  );
}
