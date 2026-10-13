import { useState } from "react";

import { t } from "../i18n/t.ts";
import { STATE_STYLES } from "../lib/states.ts";
import type { Segment } from "../lib/timeline.ts";
import { formatDuration, formatTime } from "../lib/time.ts";

interface StateTimelineProps {
  segments: Segment[];
  fromMs: number;
  toMs: number;
  zone: string;
}

function describe(segment: Segment, zone: string): string {
  const text = t("detail.segment", {
    state: t(STATE_STYLES[segment.state].label),
    start: formatTime(segment.startMs, zone),
    duration: formatDuration((segment.endMs - segment.startMs) / 1000),
  });
  return segment.alarm ? `${text} · ${t("machine.alarm", { code: segment.alarm })}` : text;
}

/** A horizontal bar: one coloured piece per state; hover or focus shows the details. */
export function StateTimeline({ segments, fromMs, toMs, zone }: StateTimelineProps) {
  const [active, setActive] = useState<Segment | null>(null);
  const total = Math.max(1, toMs - fromMs);

  return (
    <div>
      <div className="flex h-12 w-full overflow-hidden rounded-md border border-gray-300">
        {segments.map((segment) => {
          const label = describe(segment, zone);
          return (
            <button
              key={`${segment.startMs}-${segment.state}`}
              type="button"
              aria-label={label}
              title={label}
              onMouseEnter={() => setActive(segment)}
              onFocus={() => setActive(segment)}
              onMouseLeave={() => setActive(null)}
              className={`h-full ${STATE_STYLES[segment.state].solid} focus:outline-2 focus:outline-black`}
              style={{ width: `${((segment.endMs - segment.startMs) / total) * 100}%` }}
            />
          );
        })}
      </div>
      <div className="mt-1 flex justify-between text-base text-gray-600">
        <span>{formatTime(fromMs, zone)}</span>
        <span>{formatTime(toMs, zone)}</span>
      </div>
      <p className="mt-2 min-h-7 text-lg text-gray-800" aria-live="polite">
        {active ? describe(active, zone) : ""}
      </p>
    </div>
  );
}
