/** Labels and styles for maintenance actions: every status and priority has colour + icon + text. */
import type { ActionStatus, Priority } from "../api/maintenanceTypes.ts";
import type { MessageKey } from "../i18n/en.ts";
import { t } from "../i18n/t.ts";

export const statusLabel = (status: ActionStatus): string => t(`mstatus.${status}` as MessageKey);
export const priorityLabel = (priority: Priority): string => t(`mpriority.${priority}` as MessageKey);

export const STATUS_STYLE: Record<ActionStatus, string> = {
  requested: "bg-gray-200 text-gray-900",
  assigned: "bg-blue-100 text-blue-900",
  in_progress: "bg-amber-100 text-amber-900",
  waiting: "bg-purple-100 text-purple-900",
  done: "bg-green-100 text-green-900",
  verified: "bg-green-700 text-white",
  cancelled: "bg-gray-100 text-gray-500 line-through",
};

export const PRIORITY_STYLE: Record<Priority, string> = {
  urgent: "bg-red-700 text-white",
  high: "bg-orange-200 text-orange-950",
  medium: "bg-yellow-100 text-yellow-900",
  low: "bg-gray-100 text-gray-700",
};
