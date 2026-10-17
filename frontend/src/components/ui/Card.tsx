import type { ReactNode } from "react";

import { cn } from "../../lib/cn.ts";

interface CardProps {
  title?: ReactNode;
  /** Small controls on the right of the title (e.g. a group-by switch). */
  actions?: ReactNode;
  className?: string;
  children?: ReactNode;
  "data-testid"?: string;
}

/** A content block: surface colour, subtle border, no heavy shadow. */
export function Card({ title, actions, className, children, ...rest }: CardProps) {
  return (
    <section className={cn("rounded-card border border-line bg-surface p-4 sm:p-6", className)} {...rest}>
      {(title || actions) && (
        <header className="mb-4 flex flex-wrap items-center justify-between gap-3">
          {title && <h2 className="text-title font-semibold text-ink">{title}</h2>}
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  );
}
