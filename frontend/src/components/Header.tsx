import type { ReactNode } from "react";

import type { CurrentShift } from "../api/types.ts";
import { t } from "../i18n/t.ts";
import { formatClock, formatShortDuration, formatTime, secondsBetween } from "../lib/time.ts";

interface HeaderProps {
  factoryName: string;
  lineName: string;
  zone: string;
  shift: CurrentShift | null | undefined;
  nowMs: number;
  live?: ReactNode;
}

export function Header({ factoryName, lineName, zone, shift, nowMs, live }: HeaderProps) {
  return (
    <header className="flex flex-wrap items-center justify-between gap-4 rounded-xl bg-gray-900 px-5 py-3 text-white">
      <div>
        <p className="text-lg text-gray-300">{factoryName}</p>
        <h1 className="text-3xl font-bold">{lineName}</h1>
      </div>
      <div className="text-xl">
        {shift ? (
          <>
            <p className="font-semibold">
              {t("shift.label", {
                name: shift.name,
                start: formatTime(shift.start, zone),
                end: formatTime(shift.end, zone),
              })}
            </p>
            <p className="text-gray-300">
              {t("shift.remaining", {
                duration: formatShortDuration(-secondsBetween(shift.end, nowMs)),
              })}
            </p>
          </>
        ) : (
          <p className="text-gray-300">{t("shift.none")}</p>
        )}
      </div>
      <div className="text-right">
        <p className="text-4xl font-bold tabular-nums">{formatClock(nowMs, zone)}</p>
        <p className="text-base text-gray-300">{t("time.zone", { zone })}</p>
      </div>
      <div className="flex items-center gap-3">
        {live}
      </div>
    </header>
  );
}
