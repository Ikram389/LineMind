import { SlidersHorizontal } from "lucide-react";
import { type ReactNode, useState } from "react";

import { t } from "../../i18n/t.ts";
import { Button } from "./Button.tsx";

interface FilterBarProps {
  /** Always visible: quick ranges and the date range. */
  children: ReactNode;
  /** Less used filters, folded behind "More filters" (open when any of them is set). */
  more?: ReactNode;
  moreActive?: boolean;
  actions?: ReactNode;
}

/** One filter row for every analysis page; extra filters fold away. */
export function FilterBar({ children, more, moreActive = false, actions }: FilterBarProps) {
  const [open, setOpen] = useState(moreActive);
  return (
    <section aria-label={t("ui.filters")} className="rounded-card border border-line bg-surface p-4">
      <div className="flex flex-wrap items-end gap-3">
        {children}
        {more && (
          <Button
            variant="ghost"
            icon={<SlidersHorizontal className="h-5 w-5" />}
            aria-expanded={open}
            onClick={() => setOpen((v) => !v)}
          >
            {open ? t("ui.fewerFilters") : t("ui.moreFilters")}
          </Button>
        )}
        {actions && <div className="ml-auto flex flex-wrap items-end gap-2">{actions}</div>}
      </div>
      {more && open && <div className="mt-4 flex flex-wrap items-end gap-3 border-t border-line pt-4">{more}</div>}
    </section>
  );
}
