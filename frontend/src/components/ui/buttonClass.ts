/** Button looks, shared by <Button> and links that look like buttons. */
import { cn } from "../../lib/cn.ts";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
/** md = 44 px (the minimum touch target), lg = 56 px (operator actions on tablets),
 *  tile = 56 px with body text, for grids of choices (e.g. downtime reasons). */
export type ButtonSize = "md" | "lg" | "tile";

const VARIANTS: Record<ButtonVariant, string> = {
  primary: "border border-transparent bg-accent text-on-accent hover:bg-accent-hover",
  secondary: "border border-line-strong bg-surface text-ink hover:bg-surface-muted",
  ghost: "border border-transparent bg-transparent text-ink hover:bg-surface-muted",
  danger: "border border-critical bg-surface text-critical hover:bg-critical-soft",
};
const SIZES: Record<ButtonSize, string> = {
  md: "min-h-11 gap-2 px-4 text-body",
  lg: "min-h-14 gap-3 px-6 text-title",
  tile: "min-h-14 gap-2 px-4 py-2 text-body",
};

/** The classes of a button, for links that look like buttons. */
export function buttonClass(variant: ButtonVariant = "secondary", size: ButtonSize = "md", extra = ""): string {
  return cn(
    "inline-flex items-center justify-center rounded-control font-semibold transition-colors",
    "disabled:cursor-not-allowed disabled:opacity-50",
    VARIANTS[variant],
    SIZES[size],
    extra,
  );
}
