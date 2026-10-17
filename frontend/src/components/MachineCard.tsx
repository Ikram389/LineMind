import { Flag, OctagonAlert } from "lucide-react";
import { Link } from "react-router";

import type { MachineStatus } from "../api/types.ts";
import { t } from "../i18n/t.ts";
import { alarmToShow } from "../lib/alarms.ts";
import { cn } from "../lib/cn.ts";
import { STATE_STYLES, effectiveState } from "../lib/states.ts";
import { formatDuration, formatShortDuration, secondsBetween } from "../lib/time.ts";

interface MachineCardProps {
  machine: MachineStatus;
  staleAfterSeconds: number;
  nowMs: number; // server time
  shiftStart: string | null;
  isFirstStop?: boolean;
  href?: string;
}

export function MachineCard({
  machine,
  staleAfterSeconds,
  nowMs,
  shiftStart,
  isFirstStop = false,
  href,
}: MachineCardProps) {
  const { state, since } = effectiveState(machine, staleAfterSeconds, nowMs);
  const style = STATE_STYLES[state];
  const Icon = style.Icon;
  const alarm = alarmToShow(machine, state, shiftStart);

  const content = (
    <article
      data-testid={`machine-${machine.external_id}`}
      data-state={state}
      data-first-stop={isFirstStop || undefined}
      className={cn(
        "flex h-full flex-col gap-3 rounded-card border-2 border-t-8 bg-surface p-4",
        style.border,
        isFirstStop && "outline-4 outline-offset-2 outline-critical",
      )}
    >
      <header className="min-w-0">
        <p className="text-caption font-semibold uppercase tracking-wide text-ink-muted">{machine.external_id}</p>
        <h3 className="truncate text-title font-bold text-ink">{machine.name}</h3>
      </header>

      <div className={cn("flex min-w-0 flex-col gap-1 rounded-control px-3 py-2", style.soft)}>
        <p className={cn("flex items-center gap-2 text-body font-extrabold uppercase tracking-wide break-words", style.text)}>
          <Icon aria-hidden data-icon={state} className="h-5 w-5 shrink-0" />
          <span>{t(style.label)}</span>
        </p>
        {since && (
          <p className="text-body tabular-nums text-ink">
            {t("machine.since", { duration: formatDuration(secondsBetween(since, nowMs)) })}
          </p>
        )}
        {state === "unknown" && <p className="text-small text-ink-muted">{t("state.unknownHint")}</p>}
      </div>

      <p className="flex flex-col">
        <span className="text-small text-ink-muted">{t("machine.shiftCount")}</span>
        <span className="text-title font-bold tabular-nums text-ink">
          {machine.shift_count === null ? t("machine.noShift") : machine.shift_count.toLocaleString("en-GB")}
        </span>
      </p>

      {alarm?.kind === "current" && (
        <p className="flex items-center gap-2 rounded-control bg-critical px-3 py-1.5 text-body font-bold text-surface">
          <OctagonAlert aria-hidden className="h-5 w-5 shrink-0" />
          {t("machine.alarm", { code: alarm.code })}
        </p>
      )}
      {alarm?.kind === "last" && (
        <p className="text-small text-ink-muted">
          {t("machine.lastAlarm", {
            code: alarm.code,
            ago: formatShortDuration(secondsBetween(alarm.at, nowMs)),
          })}
        </p>
      )}

      {isFirstStop && (
        <p className="mt-auto flex items-center justify-center gap-2 rounded-control bg-critical-soft px-2 py-1.5 text-small font-bold uppercase text-critical">
          <Flag aria-hidden className="h-4 w-4 shrink-0" />
          {t("machine.firstStop")}
        </p>
      )}
    </article>
  );

  if (!href) return content;
  return (
    <Link to={href} aria-label={t("machine.open", { name: machine.name })} className="block h-full rounded-card hover:opacity-90">
      {content}
    </Link>
  );
}
