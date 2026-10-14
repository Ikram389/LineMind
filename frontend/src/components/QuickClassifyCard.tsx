import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { getSuggestedReasons } from "../api/downtime.ts";
import { t } from "../i18n/t.ts";
import type { ClassifyTarget } from "../lib/classifyTarget.ts";
import { formatDuration } from "../lib/time.ts";
import { useClassify } from "../lib/useClassify.ts";

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
    <article className="flex flex-col gap-3 rounded-xl border-4 border-amber-500 bg-white p-4 shadow-lg">
      {event.role_in_incident === "secondary_breakdown" && (
        <p className="text-base font-semibold uppercase text-amber-800">{t("prompt.secondary")}</p>
      )}
      <p className="text-2xl font-bold text-gray-900">
        {t("prompt.question", { machine: event.machine.name })}{" "}
        <span className="font-normal text-gray-700">
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
            className="min-h-16 rounded-lg bg-blue-700 px-5 py-3 text-xl font-semibold text-white disabled:opacity-60"
          >
            {reason.name}
          </button>
        ))}
        <button
          type="button"
          onClick={onMore}
          className="min-h-16 rounded-lg border-2 border-blue-700 px-5 py-3 text-xl font-semibold text-blue-800"
        >
          {t("prompt.more")}
        </button>
        {onLater && (
          <button
            type="button"
            onClick={onLater}
            className="ml-auto min-h-16 rounded-lg px-5 py-3 text-xl text-gray-700 underline"
          >
            {t("prompt.later")}
          </button>
        )}
      </div>
      {error && (
        <p role="alert" className="text-lg text-red-700">
          {t("classify.failed")}
        </p>
      )}
    </article>
  );
}
