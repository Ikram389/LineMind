/** Formatting for the quality screens (rates come from the backend as fractions). */
import type { InspectionResult } from "../api/qualityTypes.ts";
import type { MessageKey } from "../i18n/en.ts";
import { t } from "../i18n/t.ts";

export function formatRate(rate: number | null | undefined, digits = 2): string {
  if (rate === null || rate === undefined) return "–";
  return `${(rate * 100).toFixed(digits)}%`;
}

export const formatCount = (value: number): string => value.toLocaleString("en-GB");

/** "Not reviewed", "Confirmed", "False reject" or "Reclassified as Q03". */
export function reviewLabel(result: Pick<InspectionResult, "review">): string {
  const review = result.review;
  if (!review) return t("qtable.notReviewed");
  if (review.verdict === "reclassified") {
    return t("verdict.reclassified", { code: review.corrected_defect_type?.code ?? "?" });
  }
  return t(`verdict.${review.verdict}` as MessageKey);
}
