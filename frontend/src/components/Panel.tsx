import type { ReactNode } from "react";

import { t } from "../i18n/t.ts";
import { Card } from "./ui/Card.tsx";
import { EmptyState, ErrorState, Skeleton } from "./ui/Feedback.tsx";

interface PanelProps {
  title?: string;
  isLoading?: boolean;
  isError?: boolean;
  isEmpty?: boolean;
  emptyText?: string;
  className?: string;
  /** Controls on the right of the title. */
  actions?: ReactNode;
  children?: ReactNode;
}

/** A card with consistent loading (skeleton), error and empty states. */
export function Panel({
  title,
  isLoading = false,
  isError = false,
  isEmpty = false,
  emptyText,
  className = "",
  actions,
  children,
}: PanelProps) {
  let body: ReactNode = children;
  if (isLoading) body = <Skeleton />;
  else if (isError) body = <ErrorState />;
  else if (isEmpty) body = <EmptyState title={emptyText ?? t("panel.empty")} />;

  return (
    <Card title={title} actions={actions} className={className}>
      {body}
    </Card>
  );
}
