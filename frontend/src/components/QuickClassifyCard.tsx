import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { getSuggestedReasons } from "../api/downtime.ts";
import { t } from "../i18n/t.ts";
import type { ClassifyTarget } from "../lib/classifyTarget.ts";
import { formatDuration } from "../lib/time.ts";
import { useClassify } from "../lib/useClassify.ts";
import { buttonClass } from "./ui/buttonClass.ts";

interface QuickClassifyCardProps {
  event: ClassifyTarget;
  onMore: () => void;
  onDone?: (reasonName: string) => void;
  onLater?: () => void;
  /** Big buttons for the most likely reasons. */
  buttons?: number;
}

/** "Why did the Labeler stop? (3 min 12 s, alarm E-204)" with one-tap reasons. */
export function QuickClassifyCard({ event, onMore, onDone, onLater, buttons = 4 }: QuickClassifyCardProps) {
  const suggestions = useQuery({
    queryKey: ["suggestedReasons", event.id],
    queryFn: () => getSuggestedReasons(event.id),
  });
  const classify = useClassify();
  const [error, setError] = useState(false);
  const duration = formatDuration(event.duration_seconds);

  async function choose(reasonId: number, reasonName: string) {
    setError(false);
    try {
      await classify.mutateAsync({ eventIds: [event.id], reason: reasonId, comment: "" });
      onDone?.(reasonName);
    } catch {
      setError(true);
    }
  }

  return (
    <article className="flex flex-col gap-4 rounded-card border-2 border-l-8 border-warning bg-surface p-4 shadow-lg sm:p-6">
      {event.role_in_incident === "secondary_breakdown" && (
        <p className="text-small font-semibold uppercase text-warning">{t("prompt.secondary")}</p>
      )}
      <p className="text-title font-bold text-ink">
        {t("prompt.question", { machine: event.machine.name })}{" "}
        <span className="font-normal text-ink-muted">
          (
          {event.alarm_code
            ? t("prompt.detailsAlarm", { duration, code: event.alarm_code })
            : t("prompt.details", { duration })}
          )
        </span>
      </p>
      <div className="flex flex-wrap gap-3">
        {suggestions.data?.slice(0, buttons).map((reason) => (
          <button
            key={reason.id}
            type="button"
            disabled={classify.isPending}
            onClick={() => void choose(reason.id, reason.name)}
            className={buttonClass("primary", "lg")}
          >
            {reason.name}
          </button>
        ))}
        <button
          type="button"
          onClick={onMore}
          className={buttonClass("secondary", "lg")}
        >
          {t("prompt.more")}
        </button>
        {onLater && (
          <button
            type="button"
            onClick={onLater}
            className={buttonClass("ghost", "lg", "ml-auto underline")}
          >
            {t("prompt.later")}
          </button>
        )}
      </div>
      {error && (
        <p role="alert" className="text-body font-semibold text-critical">
          {t("classify.failed")}
        </p>
      )}
    </article>
  );
}
