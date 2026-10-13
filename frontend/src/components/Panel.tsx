import type { ReactNode } from "react";

import { t } from "../i18n/t.ts";

interface PanelProps {
  title?: string;
  isLoading?: boolean;
  isError?: boolean;
  isEmpty?: boolean;
  emptyText?: string;
  className?: string;
  children?: ReactNode;
}

/** A titled box with consistent loading, error and empty states. */
export function Panel({
  title,
  isLoading = false,
  isError = false,
  isEmpty = false,
  emptyText,
  className = "",
  children,
}: PanelProps) {
  let body: ReactNode = children;
  if (isLoading) body = <p className="text-lg text-gray-500">{t("panel.loading")}</p>;
  else if (isError) body = <p className="text-lg text-red-700" role="alert">{t("panel.error")}</p>;
  else if (isEmpty) body = <p className="text-lg text-gray-500">{emptyText ?? t("panel.empty")}</p>;

  return (
    <section className={`rounded-xl border border-gray-200 bg-white p-4 shadow-sm ${className}`}>
      {title && <h2 className="mb-3 text-xl font-semibold text-gray-800">{title}</h2>}
      {body}
    </section>
  );
}
