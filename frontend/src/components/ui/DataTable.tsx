import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";
import { type ReactNode, useMemo, useState } from "react";

import { t } from "../../i18n/t.ts";
import { cn } from "../../lib/cn.ts";
import { Button } from "./Button.tsx";

export interface Column<T> {
  key: string;
  header: ReactNode;
  render: (row: T) => ReactNode;
  /** Makes the header sortable: the value to sort by (client-side) … */
  sortValue?: (row: T) => string | number | null;
  /** … or, with server-side sorting, the column is sortable when this is true. */
  sortable?: boolean;
  align?: "left" | "right";
  className?: string;
}

export interface Sort {
  key: string;
  direction: "asc" | "desc";
}

interface DataTableProps<T> {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string | number;
  caption?: string;
  /** Server-side sorting: the current sort and how to change it. Without it, sorting is local. */
  sort?: Sort | null;
  onSort?: (sort: Sort) => void;
  pagination?: { total: number; offset: number; limit: number; onPage: (offset: number) => void };
  rowTestId?: (row: T) => string;
  empty?: ReactNode;
}

/** A table with a sticky header, row hover, sortable headers and pagination. */
export function DataTable<T>({
  columns,
  rows,
  rowKey,
  caption,
  sort,
  onSort,
  pagination,
  rowTestId,
  empty,
}: DataTableProps<T>) {
  const [localSort, setLocalSort] = useState<Sort | null>(null);
  const current = onSort ? (sort ?? null) : localSort;

  const sorted = useMemo(() => {
    if (onSort || !localSort) return rows;
    const column = columns.find((c) => c.key === localSort.key);
    if (!column?.sortValue) return rows;
    const value = column.sortValue;
    const factor = localSort.direction === "asc" ? 1 : -1;
    return [...rows].sort((a, b) => {
      const x = value(a);
      const y = value(b);
      if (x === y) return 0;
      if (x === null) return 1;
      if (y === null) return -1;
      return x < y ? -factor : factor;
    });
  }, [rows, columns, localSort, onSort]);

  function toggle(key: string) {
    const next: Sort = {
      key,
      direction: current?.key === key && current.direction === "asc" ? "desc" : "asc",
    };
    if (onSort) onSort(next);
    else setLocalSort(next);
  }

  if (rows.length === 0 && empty) return <>{empty}</>;

  return (
    <div className="flex flex-col gap-3">
      <div className="max-h-[70vh] overflow-auto rounded-control border border-line">
        <table className="w-full border-collapse text-left text-body">
          {caption && <caption className="sr-only">{caption}</caption>}
          <thead className="sticky top-0 z-10 bg-surface-muted">
            <tr>
              {columns.map((column) => {
                const sortable = Boolean(column.sortValue || column.sortable);
                const direction = current?.key === column.key ? current.direction : null;
                const Arrow = direction === "asc" ? ArrowUp : direction === "desc" ? ArrowDown : ArrowUpDown;
                return (
                  <th
                    key={column.key}
                    scope="col"
                    aria-sort={direction === "asc" ? "ascending" : direction === "desc" ? "descending" : undefined}
                    className={cn(
                      "border-b border-line px-3 py-2 text-small font-semibold text-ink-muted",
                      column.align === "right" && "text-right",
                    )}
                  >
                    {sortable ? (
                      <button
                        type="button"
                        onClick={() => toggle(column.key)}
                        className="inline-flex min-h-11 items-center gap-1 font-semibold hover:text-ink"
                      >
                        {column.header}
                        <Arrow aria-hidden className={cn("h-4 w-4", direction ? "text-accent" : "opacity-50")} />
                      </button>
                    ) : (
                      column.header
                    )}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {sorted.map((row) => (
              <tr
                key={rowKey(row)}
                data-testid={rowTestId?.(row)}
                className="border-b border-line last:border-b-0 hover:bg-surface-muted"
              >
                {columns.map((column) => (
                  <td
                    key={column.key}
                    className={cn("h-12 px-3 py-2 align-middle text-ink", column.align === "right" && "text-right tabular-nums", column.className)}
                  >
                    {column.render(row)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {pagination && pagination.total > pagination.limit && (
        <nav aria-label={t("ui.pages")} className="flex items-center gap-3 text-body text-ink-muted">
          <Button
            disabled={pagination.offset === 0}
            onClick={() => pagination.onPage(Math.max(0, pagination.offset - pagination.limit))}
          >
            {t("table.previous")}
          </Button>
          <span className="tabular-nums">
            {t("table.page", {
              from: pagination.offset + 1,
              to: Math.min(pagination.offset + pagination.limit, pagination.total),
              total: pagination.total,
            })}
          </span>
          <Button
            disabled={pagination.offset + pagination.limit >= pagination.total}
            onClick={() => pagination.onPage(pagination.offset + pagination.limit)}
          >
            {t("table.next")}
          </Button>
        </nav>
      )}
    </div>
  );
}
