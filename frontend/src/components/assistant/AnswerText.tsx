import { CircleHelp, TriangleAlert } from "lucide-react";
import type { ReactNode } from "react";

import type { CheckedNumber, NumberCheck } from "../../api/assistantTypes.ts";
import { t } from "../../i18n/t.ts";

/** Verified numbers are plain text. Unverified ones and numbers taken only from the
 *  question are marked with an icon and words, never colour alone. */
function Marked({ item }: { item: CheckedNumber }) {
  if (item.status === "unverified") {
    return (
      <mark
        data-number="unverified"
        title={t("assistant.notVerifiedHelp")}
        className="inline-flex items-baseline gap-0.5 rounded bg-warning-soft px-0.5 text-ink underline decoration-warning decoration-dotted decoration-2 underline-offset-4"
      >
        {item.text}
        <TriangleAlert aria-hidden className="h-3.5 w-3.5 self-center text-warning" />
        <span className="text-caption font-semibold text-warning">({t("assistant.notVerified")})</span>
      </mark>
    );
  }
  return (
    <mark
      data-number="from_question"
      title={t("assistant.fromQuestionHelp")}
      className="inline-flex items-baseline gap-0.5 rounded border border-dashed border-line-strong bg-transparent px-0.5 text-ink"
    >
      {item.text}
      <CircleHelp aria-hidden className="h-3.5 w-3.5 self-center text-ink-muted" />
      <span className="text-caption font-semibold text-ink-muted">({t("assistant.fromQuestion")})</span>
    </mark>
  );
}

/** The answer text with its checked numbers marked (positions come from the server). */
export function AnswerText({ content, check }: { content: string; check?: NumberCheck | Record<string, never> }) {
  const items = ("items" in (check ?? {}) ? (check as NumberCheck).items : [])
    .filter((i) => i.status !== "verified")
    .sort((a, b) => a.start - b.start);
  const parts: ReactNode[] = [];
  let at = 0;
  for (const item of items) {
    if (item.start < at || item.end > content.length) continue;
    parts.push(content.slice(at, item.start));
    parts.push(<Marked key={item.start} item={item} />);
    at = item.end;
  }
  parts.push(content.slice(at));
  return <div className="whitespace-pre-line text-body leading-7 text-ink" dir="auto">{parts}</div>;
}
