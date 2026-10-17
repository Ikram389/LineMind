/** Drawer (side panel) and Dialog (centred, a bottom sheet on small screens). */
import { X } from "lucide-react";
import { type ReactNode, useEffect, useId, useRef } from "react";

import { t } from "../../i18n/t.ts";
import { cn } from "../../lib/cn.ts";

interface OverlayProps {
  title: ReactNode;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  /** Shown under the title. */
  subtitle?: ReactNode;
  "data-testid"?: string;
}

/** Closes on Escape and moves focus into the panel when it opens. */
function useOverlay(onClose: () => void) {
  const ref = useRef<HTMLElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    ref.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      previous?.focus?.();
    };
  }, [onClose]);
  return ref;
}

function Header({ id, title, subtitle, onClose }: { id: string; title: ReactNode; subtitle?: ReactNode; onClose: () => void }) {
  return (
    <header className="flex items-start justify-between gap-3 border-b border-line px-6 py-4">
      <div>
        <h2 id={id} className="text-title font-bold text-ink">
          {title}
        </h2>
        {subtitle && <div className="mt-1 text-body text-ink-muted">{subtitle}</div>}
      </div>
      <button
        type="button"
        onClick={onClose}
        aria-label={t("ui.close")}
        className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-control text-ink-muted hover:bg-surface-muted"
      >
        <X aria-hidden className="h-6 w-6" />
      </button>
    </header>
  );
}

export function Drawer({ title, subtitle, onClose, children, footer, ...rest }: OverlayProps) {
  const id = useId();
  const ref = useOverlay(onClose);
  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/40" role="presentation" onClick={onClose}>
      <aside
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby={id}
        tabIndex={-1}
        onClick={(event) => event.stopPropagation()}
        className="flex h-full w-full max-w-xl flex-col border-l border-line bg-canvas shadow-xl"
        {...rest}
      >
        <Header id={id} title={title} subtitle={subtitle} onClose={onClose} />
        <div className="flex-1 overflow-y-auto p-6">{children}</div>
        {footer && <footer className="border-t border-line px-6 py-4">{footer}</footer>}
      </aside>
    </div>
  );
}

export function Dialog({ title, subtitle, onClose, children, footer, size = "md", ...rest }: OverlayProps & { size?: "md" | "lg" }) {
  const id = useId();
  const ref = useOverlay(onClose);
  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 sm:items-center sm:p-6"
      role="presentation"
      onClick={onClose}
    >
      <section
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby={id}
        tabIndex={-1}
        onClick={(event) => event.stopPropagation()}
        className={cn(
          "flex max-h-[92vh] w-full flex-col rounded-t-card border border-line bg-surface shadow-xl sm:rounded-card",
          size === "lg" ? "sm:max-w-4xl" : "sm:max-w-2xl",
        )}
        {...rest}
      >
        <Header id={id} title={title} subtitle={subtitle} onClose={onClose} />
        <div className="overflow-y-auto p-6">{children}</div>
        {footer && <footer className="flex flex-wrap justify-end gap-3 border-t border-line px-6 py-4">{footer}</footer>}
      </section>
    </div>
  );
}
