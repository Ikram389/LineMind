import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleAlert, OctagonAlert } from "lucide-react";

import { acknowledgeAlert, getAlert } from "../../api/alerts.ts";
import { queryKeys } from "../../api/queryKeys.ts";
import type { AlertSummary } from "../../api/types.ts";
import { t } from "../../i18n/t.ts";
import { alertMessage, severityLabel, SEVERITY_STYLE } from "../../lib/alertText.ts";
import { formatTime } from "../../lib/time.ts";

interface AlertBannerProps {
  alert: AlertSummary;
  zone: string;
  onHide: () => void;
}

/** A non-blocking banner on the line overview when a warning or critical alert opens. */
export function AlertBanner({ alert, zone, onHide }: AlertBannerProps) {
  const queryClient = useQueryClient();
  // The full alert says whether this user may acknowledge it.
  const full = useQuery({ queryKey: [...queryKeys.alerts, "one", alert.alert_id], queryFn: () => getAlert(alert.alert_id) });
  const ack = useMutation({
    mutationFn: () => acknowledgeAlert(alert.alert_id, ""),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: queryKeys.alerts }),
  });
  const Icon = alert.severity === "critical" ? OctagonAlert : CircleAlert;
  const acknowledged = ack.isSuccess || full.data?.status === "acknowledged";

  return (
    <aside
      role="status"
      aria-label={t("banner.label")}
      data-testid="alert-banner"
      className={`flex flex-wrap items-center justify-between gap-3 rounded-xl border-l-8 p-4 shadow ${SEVERITY_STYLE[alert.severity]}`}
    >
      <p className="flex items-center gap-3 text-xl font-semibold">
        <Icon aria-hidden className="h-8 w-8 shrink-0" />
        <span>
          {severityLabel(alert.severity)}: {alertMessage(alert.message_key, alert.message_values)} —{" "}
          {t("banner.since", { time: formatTime(alert.condition_since, zone) })}
        </span>
      </p>
      <div className="flex gap-2">
        {acknowledged ? (
          <span className="self-center text-lg font-semibold">✓ {t("banner.acknowledged")}</span>
        ) : (
          full.data?.can_acknowledge && (
            <button
              type="button"
              onClick={() => ack.mutate()}
              disabled={ack.isPending}
              className="min-h-14 rounded-xl bg-gray-900 px-6 text-xl font-bold text-white"
            >
              ✓ {t("alerts.acknowledge")}
            </button>
          )
        )}
        <button type="button" onClick={onHide} className="min-h-14 rounded-xl border-2 border-gray-500 px-4 text-lg">
          {t("banner.hide")}
        </button>
      </div>
    </aside>
  );
}
