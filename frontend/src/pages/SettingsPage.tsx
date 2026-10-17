import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { getPreferences, updatePreferences } from "../api/alerts.ts";
import { ALERT_SEVERITIES, type NotificationPreferences } from "../api/alertTypes.ts";
import { queryKeys } from "../api/queryKeys.ts";
import { Panel } from "../components/Panel.tsx";
import { Card } from "../components/ui/Card.tsx";
import { PageHeader } from "../components/ui/PageHeader.tsx";
import { SegmentedControl } from "../components/ui/Choice.tsx";
import { controlClass } from "../components/ui/Field.tsx";
import { buttonClass } from "../components/ui/buttonClass.ts";
import { t } from "../i18n/t.ts";
import { severityLabel } from "../lib/alertText.ts";
import { type Theme, useTheme } from "../lib/theme.ts";

const field = controlClass;

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
    <main className="flex flex-col gap-6 p-4 sm:p-6">
      <PageHeader title={t("settings.title")} />
      <AppearanceCard />
      <Panel title={t("settings.notifications")} isLoading={prefs.isLoading} isError={prefs.isError}>
        {value && (
          <form
            className="flex flex-col gap-4"
            onSubmit={(e) => {
              e.preventDefault();
              save.mutate(value);
            }}
          >
            <label className="flex max-w-md flex-col gap-1 text-body font-semibold text-ink">
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
              <span className="text-small text-ink-muted">{t("settings.inAppNote")}</span>
            </label>
            <label className="flex max-w-md flex-col gap-1 text-body font-semibold text-ink">
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
              <button type="submit" disabled={save.isPending} className={buttonClass("primary")}>
                {t("settings.save")}
              </button>
              {save.isSuccess && <p role="status" className="text-body font-semibold text-running">{t("settings.saved")}</p>}
            </div>
          </form>
        )}
      </Panel>
    </main>
  );
}

/** Light or dark, remembered for this user in this browser. */
function AppearanceCard() {
  const [theme, setTheme] = useTheme();
  return (
    <Card title={t("theme.title")}>
      <div className="flex flex-col gap-2">
        <SegmentedControl<Theme>
          label={t("theme.label")}
          value={theme}
          onChange={setTheme}
          options={[
            { value: "light", label: t("theme.light"), testId: "theme-light" },
            { value: "dark", label: t("theme.dark"), testId: "theme-dark" },
          ]}
        />
        <p className="text-small text-ink-muted">{t("theme.note")}</p>
      </div>
    </Card>
  );
}
