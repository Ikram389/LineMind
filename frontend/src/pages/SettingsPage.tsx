import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { getPreferences, updatePreferences } from "../api/alerts.ts";
import { ALERT_SEVERITIES, type NotificationPreferences } from "../api/alertTypes.ts";
import { queryKeys } from "../api/queryKeys.ts";
import { Panel } from "../components/Panel.tsx";
import { t } from "../i18n/t.ts";
import { severityLabel } from "../lib/alertText.ts";

const field = "rounded-lg border border-gray-300 bg-white px-3 py-2 text-lg";

/** The signed-in user's notification preferences. */
export function SettingsPage() {
  const queryClient = useQueryClient();
  const prefs = useQuery({ queryKey: queryKeys.preferences, queryFn: getPreferences });
  const [value, setValue] = useState<NotificationPreferences | null>(null);
  useEffect(() => {
    if (prefs.data) setValue(prefs.data);
  }, [prefs.data]);
  const save = useMutation({
    mutationFn: (input: NotificationPreferences) => updatePreferences(input),
    onSuccess: (data) => queryClient.setQueryData(queryKeys.preferences, data),
  });

  return (
    <main className="flex min-h-screen flex-col gap-4 bg-gray-100 p-4">
      <h1 className="text-3xl font-bold">{t("settings.title")}</h1>
      <Panel title={t("settings.notifications")} isLoading={prefs.isLoading} isError={prefs.isError}>
        {value && (
          <form
            className="flex flex-col gap-4"
            onSubmit={(e) => {
              e.preventDefault();
              save.mutate(value);
            }}
          >
            <label className="flex flex-col gap-1 text-lg">
              {t("settings.inApp")}
              <select
                value={value.in_app_min_severity}
                onChange={(e) => setValue({ ...value, in_app_min_severity: e.target.value as NotificationPreferences["in_app_min_severity"] })}
                className={field}
              >
                {ALERT_SEVERITIES.map((s) => (
                  <option key={s} value={s}>
                    {severityLabel(s)}
                  </option>
                ))}
              </select>
              <span className="text-base text-gray-600">{t("settings.inAppNote")}</span>
            </label>
            <label className="flex flex-col gap-1 text-lg">
              {t("settings.email")}
              <select
                value={value.email_min_severity}
                onChange={(e) => setValue({ ...value, email_min_severity: e.target.value as NotificationPreferences["email_min_severity"] })}
                className={field}
              >
                <option value="off">{t("settings.off")}</option>
                {ALERT_SEVERITIES.map((s) => (
                  <option key={s} value={s}>
                    {severityLabel(s)}
                  </option>
                ))}
              </select>
            </label>
            <div className="flex items-center gap-3">
              <button type="submit" disabled={save.isPending} className="min-h-12 rounded-lg bg-blue-700 px-5 text-lg font-semibold text-white">
                {t("settings.save")}
              </button>
              {save.isSuccess && <p role="status" className="text-lg text-green-800">{t("settings.saved")}</p>}
            </div>
          </form>
        )}
      </Panel>
    </main>
  );
}
