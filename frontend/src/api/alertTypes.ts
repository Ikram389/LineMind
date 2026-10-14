/** Alerts, alert rules, notifications and preferences (build step 10a). */
import type { Role } from "./types.ts";

export type AlertSeverity = "info" | "warning" | "critical";
export const ALERT_SEVERITIES: AlertSeverity[] = ["info", "warning", "critical"];
export type AlertStatus = "open" | "acknowledged" | "resolved";
export type RuleType =
  | "long_stop"
  | "recurring_stop"
  | "machine_offline"
  | "low_oee"
  | "high_defect_rate"
  | "unclassified_stops";
export const RULE_TYPES: RuleType[] = [
  "long_stop",
  "recurring_stop",
  "machine_offline",
  "low_oee",
  "high_defect_rate",
  "unclassified_stops",
];

export type MessageValues = Record<string, string | number | null>;

export interface Alert {
  id: number;
  rule: { id: number; rule_type: RuleType; name: string };
  factory: number;
  factory_timezone: string;
  line: { id: number; name: string } | null;
  machine: { id: number; name: string } | null;
  subject: { type: string; id: number | null; key: string };
  severity: AlertSeverity;
  status: AlertStatus;
  opened_at: string;
  condition_since: string;
  message_key: string;
  message_values: MessageValues;
  acknowledged_by: string | null;
  acknowledged_at: string | null;
  acknowledge_note: string;
  resolved_at: string | null;
  resolution: "" | "auto" | "manual";
  resolved_by: string | null;
  resolution_note: string;
  escalated_at: string | null;
  last_evaluated_at: string;
  /** Whether the signed-in user may acknowledge it (the rule's roles, supervisors and above). */
  can_acknowledge: boolean;
}

export interface AppNotification {
  id: number;
  alert: Alert;
  channel: "in_app";
  reason: "opened" | "escalated";
  status: string;
  read_at: string | null;
  created_at: string;
}

export interface AlertRule {
  id: number;
  factory: number;
  line: number | null;
  machine: number | null;
  name: string;
  rule_type: RuleType;
  parameters: Record<string, string | number | null>;
  severity: AlertSeverity;
  is_enabled: boolean;
  recipient_roles: Role[];
  cooldown_minutes: number;
  escalate_after_minutes: number | null;
  escalation_roles: Role[];
  active_outside_shifts: boolean;
}

export type AlertRuleInput = Omit<AlertRule, "id">;

export interface RuleParameter {
  name: string;
  kind: string; // "integer", "float", "choice"
  required: boolean;
  default: string | number | null;
  min: number | null;
  max: number | null;
  choices: string[] | null;
  help: string;
}

export interface RuleTypeInfo {
  type: RuleType;
  time_driven: boolean;
  machine_scoped: boolean;
  parameters: RuleParameter[];
}

export interface NotificationPreferences {
  in_app_min_severity: AlertSeverity;
  email_min_severity: AlertSeverity | "off";
}

export interface Health {
  status: string;
  database: string;
  alerts?: "ok" | "stale";
  alerts_last_heartbeat?: string | null;
}
