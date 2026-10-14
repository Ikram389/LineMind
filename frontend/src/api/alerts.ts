/** Alerts, alert rules, notifications and preferences endpoints (build step 10a). */
import type {
  Alert,
  AlertRule,
  AlertRuleInput,
  AppNotification,
  Health,
  NotificationPreferences,
  RuleTypeInfo,
} from "./alertTypes.ts";
import { apiFetch } from "./client.ts";
import { type DowntimeQuery, toQueryString } from "./downtime.ts";
import type { Paginated } from "./types.ts";

export const listAlerts = (params: DowntimeQuery): Promise<Paginated<Alert>> =>
  apiFetch(`/alerts/?${toQueryString(params)}`);

export const getAlert = (id: number): Promise<Alert> => apiFetch(`/alerts/${id}/`);

export const acknowledgeAlert = (id: number, note: string): Promise<Alert> =>
  apiFetch(`/alerts/${id}/acknowledge/`, { method: "POST", body: JSON.stringify({ note }) });

export const resolveAlert = (id: number, note: string): Promise<Alert> =>
  apiFetch(`/alerts/${id}/resolve/`, { method: "POST", body: JSON.stringify({ note }) });

export const listNotifications = (limit = 8): Promise<Paginated<AppNotification>> =>
  apiFetch(`/notifications/?limit=${limit}`);

export const getUnreadCount = async (): Promise<number> =>
  (await apiFetch<{ unread_count: number }>("/notifications/unread-count/")).unread_count;

export const markNotificationRead = (id: number): Promise<{ unread_count: number }> =>
  apiFetch(`/notifications/${id}/read/`, { method: "POST" });

export const markAllNotificationsRead = (): Promise<{ unread_count: number }> =>
  apiFetch("/notifications/read-all/", { method: "POST" });

export const getPreferences = (): Promise<NotificationPreferences> =>
  apiFetch("/me/notification-preferences/");

export const updatePreferences = (
  input: Partial<NotificationPreferences>,
): Promise<NotificationPreferences> =>
  apiFetch("/me/notification-preferences/", { method: "PATCH", body: JSON.stringify(input) });

export const listAlertRules = (factoryId: number): Promise<AlertRule[]> =>
  apiFetch(`/alert-rules/?factory=${factoryId}`);

export const getRuleTypes = (): Promise<RuleTypeInfo[]> => apiFetch("/alert-rules/types/");

export const createAlertRule = (input: AlertRuleInput): Promise<AlertRule> =>
  apiFetch("/alert-rules/", { method: "POST", body: JSON.stringify(input) });

export const updateAlertRule = (id: number, input: Partial<AlertRuleInput>): Promise<AlertRule> =>
  apiFetch(`/alert-rules/${id}/`, { method: "PATCH", body: JSON.stringify(input) });

export const deleteAlertRule = (id: number): Promise<null> =>
  apiFetch(`/alert-rules/${id}/`, { method: "DELETE" });

export const getHealth = (): Promise<Health> => apiFetch("/health/");
