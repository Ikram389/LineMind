/**
 * Alert sentences, built from the alert's message key and values (never stored in English).
 * Example: alertMessage("alert.long_stop", {machine: "Labeler", minutes: 10, alarm: "E-204"}).
 */
import type { Alert, AlertSeverity, MessageValues, RuleType } from "../api/alertTypes.ts";
import { en, type MessageKey } from "../i18n/en.ts";
import { t } from "../i18n/t.ts";

export function alertMessage(key: string, values: MessageValues): string {
  const params: Record<string, string | number> = {};
  for (const [name, value] of Object.entries(values)) params[name] = value ?? "";
  params.alarm_text = values.alarm ? t("alertText.alarm", { alarm: String(values.alarm) }) : "";
  if (!(key in en)) return key;
  return t(key as MessageKey, params);
}

export const severityLabel = (severity: AlertSeverity): string => t(`severity.${severity}` as MessageKey);

export const ruleTypeLabel = (type: RuleType): string => t(`ruleType.${type}` as MessageKey);

export const SEVERITY_STYLE: Record<AlertSeverity, string> = {
  critical: "border-red-700 bg-red-50 text-red-900",
  warning: "border-amber-500 bg-amber-50 text-amber-900",
  info: "border-blue-600 bg-blue-50 text-blue-900",
};

/** Where to look at what the alert is about. */
export function subjectHref(alert: Alert): string | null {
  const line = alert.line?.id;
  if (!line) return null;
  switch (alert.subject.type) {
    case "incident":
      return `/lines/${line}/downtime?incident=${alert.subject.id ?? ""}`;
    case "downtime_event":
      return `/lines/${line}/unclassified`;
    case "machine":
      return alert.machine ? `/lines/${line}/machines/${alert.machine.id}` : `/lines/${line}`;
    case "station":
      return `/lines/${line}/quality`;
    default:
      return alert.rule.rule_type === "high_defect_rate" ? `/lines/${line}/quality` : `/lines/${line}`;
  }
}

