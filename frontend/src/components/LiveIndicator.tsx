import { LoaderCircle, Radio, WifiOff } from "lucide-react";

import { t } from "../i18n/t.ts";
import type { LiveStatus } from "../live/useLineLive.ts";

export function LiveIndicator({ status }: { status: LiveStatus }) {
  if (status === "live") {
    return (
      <span className="inline-flex items-center gap-2 rounded-full bg-green-100 px-3 py-1 text-lg font-semibold text-green-800">
        <Radio aria-hidden className="h-5 w-5" />
        {t("live.live")}
      </span>
    );
  }
  if (status === "reconnecting") {
    return (
      <span
        role="status"
        className="inline-flex items-center gap-2 rounded-full bg-amber-100 px-3 py-1 text-lg font-semibold text-amber-900"
      >
        <WifiOff aria-hidden className="h-5 w-5" />
        {t("live.reconnecting")}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-2 px-3 py-1 text-lg text-gray-600">
      <LoaderCircle aria-hidden className="h-5 w-5 animate-spin" />
      {t("live.connecting")}
    </span>
  );
}
