import { LoaderCircle, Radio, WifiOff } from "lucide-react";

import { t } from "../i18n/t.ts";
import type { LiveStatus } from "../live/useLineLive.ts";

export function LiveIndicator({ status }: { status: LiveStatus }) {
  if (status === "live") {
    return (
      <span className="inline-flex items-center gap-2 rounded-full bg-running-soft px-3 py-1 text-small font-semibold text-running">
        <Radio aria-hidden className="h-4 w-4" />
        {t("live.live")}
      </span>
    );
  }
  if (status === "reconnecting") {
    return (
      <span
        role="status"
        className="inline-flex items-center gap-2 rounded-full bg-warning-soft px-3 py-1 text-small font-semibold text-warning"
      >
        <WifiOff aria-hidden className="h-4 w-4" />
        {t("live.reconnecting")}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-2 px-3 py-1 text-small text-ink-muted">
      <LoaderCircle aria-hidden className="h-4 w-4 animate-spin" />
      {t("live.connecting")}
    </span>
  );
}
