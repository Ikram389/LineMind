import { Link } from "react-router";

import type { MachineStatus } from "../api/types.ts";
import { t } from "../i18n/t.ts";
import { alarmToShow } from "../lib/alarms.ts";
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
      className={`flex h-full min-w-[11rem] flex-col gap-2 rounded-xl border-4 p-4 ${style.card} ${
        isFirstStop ? "ring-8 ring-red-500/60 outline-4 outline-offset-4 outline-red-700" : ""
      }`}
    >
      <header>
        <p className="text-sm font-semibold uppercase tracking-wide text-gray-600">
          {machine.external_id}
        </p>
        <h3 className="text-2xl font-bold text-gray-900">{machine.name}</h3>
      </header>

      <p className={`flex items-center gap-2 text-3xl font-extrabold uppercase ${style.text}`}>
        <Icon aria-hidden data-icon={state} className="h-8 w-8 shrink-0" />
        <span>{t(style.label)}</span>
      </p>
      {since && (
        <p className="text-xl tabular-nums text-gray-800">
          {t("machine.since", { duration: formatDuration(secondsBetween(since, nowMs)) })}
        </p>
      )}
      {state === "unknown" && <p className="text-base text-gray-600">{t("state.unknownHint")}</p>}

      <p className="text-lg text-gray-800">
        <span className="text-gray-600">{t("machine.shiftCount")}: </span>
        <span className="font-semibold tabular-nums">
          {machine.shift_count === null ? t("machine.noShift") : machine.shift_count.toLocaleString("en-GB")}
        </span>
      </p>

      {alarm?.kind === "current" && (
        <p className="rounded-md bg-red-700 px-2 py-1 text-xl font-bold text-white">
          {t("machine.alarm", { code: alarm.code })}
        </p>
      )}
      {alarm?.kind === "last" && (
        <p className="text-sm text-gray-500">
          {t("machine.lastAlarm", {
            code: alarm.code,
            ago: formatShortDuration(secondsBetween(alarm.at, nowMs)),
          })}
        </p>
      )}

      {isFirstStop && (
        <p className="mt-auto rounded-md bg-red-800 px-2 py-1 text-center text-base font-bold uppercase text-white">
          {t("machine.firstStop")}
        </p>
      )}
    </article>
  );

  if (!href) return content;
  return (
    <Link to={href} aria-label={t("machine.open", { name: machine.name })} className="block h-full">
      {content}
    </Link>
  );
}
