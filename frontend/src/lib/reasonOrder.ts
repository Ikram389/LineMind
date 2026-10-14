import type { Reason, ReasonCategory } from "../api/analysisTypes.ts";
import type { DowntimeCategory } from "../api/types.ts";

/** Reason categories that usually explain each kind of stop (same as the backend). */
export const LIKELY_REASON_CATEGORIES: Record<DowntimeCategory, ReasonCategory[]> = {
  breakdown: ["mechanical", "electrical"],
  blocked: ["material", "organizational"],
  starved: ["material", "organizational"],
  planned: ["planned"],
  no_data: ["electrical"],
};

const ALL: ReasonCategory[] = [
  "mechanical",
  "electrical",
  "material",
  "quality",
  "organizational",
  "planned",
];

/** Active reasons grouped by category, the stop's likely categories first. */
export function groupReasons(
  reasons: Reason[],
  stopCategory: DowntimeCategory | null,
): { category: ReasonCategory; reasons: Reason[] }[] {
  const likely = stopCategory ? LIKELY_REASON_CATEGORIES[stopCategory] : [];
  const order = [...likely, ...ALL.filter((c) => !likely.includes(c))];
  return order
    .map((category) => ({
      category,
      reasons: reasons
        .filter((r) => r.is_active && r.category === category)
        .sort((a, b) => a.code.localeCompare(b.code)),
    }))
    .filter((group) => group.reasons.length > 0);
}

export function matchesSearch(reason: Reason, search: string): boolean {
  const needle = search.trim().toLowerCase();
  if (!needle) return true;
  return reason.name.toLowerCase().includes(needle) || reason.code.toLowerCase().includes(needle);
}
