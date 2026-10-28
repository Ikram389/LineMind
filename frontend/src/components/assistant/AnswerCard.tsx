import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  BadgeCheck,
  Bell,
  CalendarRange,
  ChevronDown,
  Factory,
  type LucideIcon,
  OctagonX,
  ThumbsDown,
  ThumbsUp,
  TimerOff,
  Wrench,
} from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";

import { sendFeedback } from "../../api/assistant.ts";
import type { AssistantMessage, SourceType } from "../../api/assistantTypes.ts";
import { queryKeys } from "../../api/queryKeys.ts";
import { t } from "../../i18n/t.ts";
import { cn } from "../../lib/cn.ts";
import { InlineNotice } from "../ui/Feedback.tsx";
import { AnswerText } from "./AnswerText.tsx";
import { progressLabel } from "./progress.ts";

const SOURCE_ICON: Record<SourceType, LucideIcon> = {
  line: Factory,
  machine: Factory,
  downtime: TimerOff,
  incident: OctagonX,
  quality: BadgeCheck,
  maintenance_action: Wrench,
  alert: Bell,
};

function formatValue(value: number | string | null, unit: string): string {
  if (value === null) return "—";
  const shown = typeof value === "number" ? value.toLocaleString("en-GB") : value;
  if (!unit) return String(shown);
  return unit === "%" ? `${shown}%` : `${shown} ${unit}`;
}

function HowIGotThis({ answer }: { answer: AssistantMessage }) {
  const [open, setOpen] = useState(false);
  const calls = answer.tool_calls;
  return (
    <div>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="inline-flex min-h-11 items-center gap-2 text-small font-semibold text-accent hover:underline"
      >
        <ChevronDown aria-hidden className={cn("h-4 w-4 transition-transform", open && "rotate-180")} />
        {t("assistant.how", { count: calls.length })}
      </button>
      {open && (
        <ol data-testid="how-i-got-this" className="mt-2 flex flex-col gap-2 border-l-2 border-line pl-4">
          {calls.length === 0 && <li className="text-small text-ink-muted">{t("assistant.howEmpty")}</li>}
          {calls.map((call) => (
            <li key={call.order} className="text-small">
              <span className="font-semibold text-ink">{progressLabel(call.name, call.name)}</span>{" "}
              <code className="text-caption text-ink-muted">{call.name}</code>
              {call.invalid && <span className="ml-2 font-semibold text-warning">({t("assistant.invalidCall")})</span>}
              <pre className="mt-1 overflow-x-auto rounded-control bg-surface-muted p-2 text-caption text-ink-muted">
                {JSON.stringify(call.arguments, null, 1)}
              </pre>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

function FeedbackButtons({ answer, conversationId }: { answer: AssistantMessage; conversationId: number }) {
  const queryClient = useQueryClient();
  const send = useMutation({
    mutationFn: (helpful: boolean) => sendFeedback(answer.id, helpful),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: queryKeys.assistantConversation(conversationId) }),
  });
  const current = send.variables ?? answer.feedback?.helpful;
  return (
    <div className="flex flex-wrap items-center gap-2" role="group" aria-label={t("assistant.helpfulQ")}>
      <span className="text-small text-ink-muted">{t("assistant.helpfulQ")}</span>
      {([true, false] as const).map((helpful) => {
        const Icon = helpful ? ThumbsUp : ThumbsDown;
        return (
          <button
            key={String(helpful)}
            type="button"
            aria-pressed={current === helpful}
            onClick={() => send.mutate(helpful)}
            className={cn(
              "inline-flex min-h-11 items-center gap-1.5 rounded-control border px-3 text-small font-semibold",
              current === helpful ? "border-accent bg-accent-soft text-accent" : "border-line-strong text-ink hover:bg-surface-muted",
            )}
          >
            <Icon aria-hidden className="h-4 w-4" />
            {helpful ? t("assistant.helpful") : t("assistant.notHelpful")}
          </button>
        );
      })}
      {send.isSuccess && <span role="status" className="text-small text-ink-muted">{t("assistant.thanks")}</span>}
    </div>
  );
}

/** One answer: range, text with checked numbers, key figures, notes, sources, trace, feedback. */
export function AnswerCard({ answer, conversationId }: { answer: AssistantMessage; conversationId: number }) {
  const check = "items" in answer.number_check ? answer.number_check : null;
  return (
    <article aria-label={t("assistant.answer")} data-testid="answer" className="flex flex-col gap-4 rounded-card border border-line bg-surface p-4 sm:p-6">
      {answer.resolved_ranges.length > 0 && (
        <p className="flex flex-wrap items-center gap-2 text-small font-semibold text-ink" data-testid="answer-range">
          <CalendarRange aria-hidden className="h-4 w-4 text-accent" />
          <span className="text-ink-muted">{t("assistant.range")}:</span>
          {answer.resolved_ranges.map((r) => r.label).join(" · ")}
        </p>
      )}

      {answer.unchecked && (
        <div data-testid="answer-unchecked">
          <InlineNotice tone="warning">{t("assistant.unchecked")}</InlineNotice>
        </div>
      )}
      <AnswerText content={answer.content} check={answer.number_check} />

      {answer.key_metrics.length > 0 && (
        <table className="w-full max-w-lg border-collapse text-small" data-testid="answer-metrics">
          <caption className="mb-1 text-left text-small font-semibold text-ink-muted">{t("assistant.metrics")}</caption>
          <thead className="sr-only">
            <tr>
              <th scope="col">{t("assistant.metric")}</th>
              <th scope="col">{t("assistant.value")}</th>
            </tr>
          </thead>
          <tbody>
            {answer.key_metrics.map((m) => (
              <tr key={m.label} className="border-b border-line last:border-b-0">
                <th scope="row" className="py-1.5 pr-4 text-left font-normal text-ink-muted">{m.label}</th>
                <td className="py-1.5 text-right font-semibold tabular-nums text-ink">{formatValue(m.value, m.unit)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {answer.warnings.length > 0 && (
        <div className="flex flex-col gap-2">
          <p className="text-small font-semibold text-ink-muted">{t("assistant.warnings")}</p>
          <ul className="flex flex-col gap-2">
            {answer.warnings.map((w) => (
              <li key={w}>
                <InlineNotice tone="warning">{w}</InlineNotice>
              </li>
            ))}
          </ul>
        </div>
      )}

      {answer.sources.length > 0 && (
        <nav aria-label={t("assistant.sources")} className="flex flex-col gap-2">
          <p className="text-small font-semibold text-ink-muted">{t("assistant.sources")}</p>
          <ul className="flex flex-wrap gap-2">
            {answer.sources.map((source) => {
              const Icon = SOURCE_ICON[source.type] ?? Factory;
              return (
                <li key={source.link}>
                  <Link
                    to={source.link}
                    data-testid={`source-${source.n}`}
                    className="inline-flex min-h-11 items-center gap-2 rounded-full border border-line-strong bg-surface px-3 text-small font-semibold text-ink hover:border-accent hover:text-accent"
                  >
                    <span className="tabular-nums text-ink-muted">[{source.n}]</span>
                    <Icon aria-hidden className="h-4 w-4" />
                    {source.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
      )}

      {check && check.items.length > 0 && (
        <p className="text-caption text-ink-muted" data-testid="number-check">
          {t("assistant.checkSummary", { count: check.items.length })}
          {check.unverified > 0 && (
            <span className="ml-1 font-semibold text-warning">· {t("assistant.checkUnverified", { count: check.unverified })}</span>
          )}
        </p>
      )}
      <p className="text-caption text-ink-muted">{t("assistant.aiNote")}</p>
      <HowIGotThis answer={answer} />
      <FeedbackButtons answer={answer} conversationId={conversationId} />
    </article>
  );
}
