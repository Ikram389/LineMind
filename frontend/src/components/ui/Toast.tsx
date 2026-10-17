/** Toast: a short message that confirms something happened, bottom-left, then fades.
 *  Tooltip: a short label shown on hover and keyboard focus. */
import { CircleCheck, X } from "lucide-react";
import { type ReactNode, useEffect, useId, useState } from "react";

import { t } from "../../i18n/t.ts";
import { cn } from "../../lib/cn.ts";

interface ToastProps {
  message: ReactNode;
  onClose: () => void;
  /** Milliseconds before it closes by itself (0: stays). */
  duration?: number;
}

export function Toast({ message, onClose, duration = 5000 }: ToastProps) {
  useEffect(() => {
    if (!duration) return;
    const timer = window.setTimeout(onClose, duration);
    return () => window.clearTimeout(timer);
  }, [duration, onClose]);
  return (
    <div
      role="status"
      className="fixed bottom-6 left-6 z-50 flex max-w-md items-center gap-3 rounded-card border border-line bg-surface px-4 py-3 text-body font-semibold text-ink shadow-lg"
    >
      <CircleCheck aria-hidden className="h-6 w-6 shrink-0 text-running" />
      <span className="flex-1">{message}</span>
      <button
        type="button"
        onClick={onClose}
        aria-label={t("ui.close")}
        className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-control text-ink-muted hover:bg-surface-muted"
      >
        <X aria-hidden className="h-5 w-5" />
      </button>
    </div>
  );
}

interface TooltipProps {
  label: string;
  children: ReactNode;
  side?: "right" | "bottom";
}

/** Wraps a focusable element; the label is also its accessible description. */
export function Tooltip({ label, children, side = "bottom" }: TooltipProps) {
  const id = useId();
  const [open, setOpen] = useState(false);
  return (
    <span
      className="relative inline-flex"
      aria-describedby={id}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={() => setOpen(false)}
    >
      {children}
      <span
        id={id}
        role="tooltip"
        className={cn(
          "pointer-events-none absolute z-50 whitespace-nowrap rounded-control bg-ink px-2 py-1 text-small font-semibold text-canvas",
          side === "right" ? "left-full top-1/2 ml-2 -translate-y-1/2" : "left-1/2 top-full mt-2 -translate-x-1/2",
          open ? "opacity-100" : "sr-only opacity-0",
        )}
      >
        {label}
      </span>
    </span>
  );
}
