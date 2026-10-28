import { CornerDownRight } from "lucide-react";

import type { MessageKey } from "../../i18n/en.ts";
import { t } from "../../i18n/t.ts";
import { StatusBadge } from "../ui/StatusBadge.tsx";
import type { StatusKind } from "../ui/status.ts";
import { Tag } from "../ui/Tag.tsx";
import { CATEGORY_KEY } from "./categories.ts";

/** A downtime category looks like the machine state it comes from (colour, icon, text). */
const CATEGORY_STATUS: Record<string, StatusKind> = {
  breakdown: "stopped",
  blocked: "blocked",
  starved: "starved",
  planned: "planned_stop",
  no_data: "unknown",
};

export function CategoryBadge({ category }: { category: string }) {
  return (
    <StatusBadge
      kind={CATEGORY_STATUS[category] ?? "stopped"}
      size="sm"
      label={t(CATEGORY_KEY[category] ?? "category.breakdown")}
    />
  );
}

/** First observed stop and secondary breakdowns need a reason; consequences never do. */
export function RoleBadge({ role }: { role: string | null }) {
  if (!role) return null;
  const label = t(`role.${role}` as MessageKey);
  if (role === "first_observed_stop") return <StatusBadge kind="critical" size="sm" label={label} />;
  if (role === "secondary_breakdown") return <StatusBadge kind="warning" size="sm" label={label} />;
  return <Tag icon={CornerDownRight}>{label}</Tag>;
}
