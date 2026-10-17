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
  /** Live status, badges and buttons, on the right. */
  actions?: ReactNode;
}

/** The overview's page header: line and factory, the shift, the factory clock and timezone. */
export function Header({ factoryName, lineName, zone, shift, nowMs, actions }: HeaderProps) {
  return (
    <header className="flex flex-wrap items-center justify-between gap-x-8 gap-y-4">
      <div className="min-w-0">
        <p className="text-body text-ink-muted">{factoryName}</p>
        <h1 className="text-page font-bold text-ink">{lineName}</h1>
      </div>
      <div className="flex flex-wrap items-center gap-x-8 gap-y-3">
        <div>
          <p className="text-small font-semibold text-ink-muted">{t("overview.shiftNow")}</p>
          {shift ? (
            <p className="text-body text-ink">
              <span className="font-semibold">
                {t("shift.label", {
                  name: shift.name,
                  start: formatTime(shift.start, zone),
                  end: formatTime(shift.end, zone),
                })}
              </span>
              <span className="text-ink-muted">
                {" · "}
                {t("shift.remaining", { duration: formatShortDuration(-secondsBetween(shift.end, nowMs)) })}
              </span>
            </p>
          ) : (
            <p className="text-body text-ink-muted">{t("shift.none")}</p>
          )}
        </div>
        <div>
          <p className="text-stat font-bold tabular-nums text-ink">{formatClock(nowMs, zone)}</p>
          <p className="text-caption text-ink-muted">{t("time.zone", { zone })}</p>
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
    </header>
  );
}
