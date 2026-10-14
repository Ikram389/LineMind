/**
 * Banners for the line overview: a warning or critical alert that opens on *this* line.
 * Removed when the alert resolves, or when the person hides it.
 */
import { useCallback, useState } from "react";

import type { AlertSummary, LiveMessage } from "../api/types.ts";

const SHOWN: ReadonlySet<string> = new Set(["warning", "critical"]);

export function useAlertBanners(lineId: number) {
  const [banners, setBanners] = useState<AlertSummary[]>([]);

  const onMessage = useCallback(
    (message: LiveMessage) => {
      if (message.type === "alert_opened") {
        const alert = message.data;
        if (alert.line_id !== lineId || !SHOWN.has(alert.severity)) return;
        setBanners((current) =>
          current.some((b) => b.alert_id === alert.alert_id) ? current : [alert, ...current],
        );
      } else if (message.type === "alert_resolved") {
        setBanners((current) => current.filter((b) => b.alert_id !== message.data.alert_id));
      }
    },
    [lineId],
  );

  const hide = useCallback((alertId: number) => {
    setBanners((current) => current.filter((b) => b.alert_id !== alertId));
  }, []);

  return { banners, onMessage, hide };
}
