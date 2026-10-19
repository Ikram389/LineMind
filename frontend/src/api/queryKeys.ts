/** TanStack Query cache keys, in one place so live updates can find the right data. */
export const queryKeys = {
  me: ["me"] as const,
  lines: ["lines"] as const,
  line: (id: number) => ["line", id] as const,
  factory: (id: number) => ["factory", id] as const,
  lineStatus: (id: number) => ["lineStatus", id] as const,
  currentShift: (factoryId: number) => ["currentShift", factoryId] as const,
  oee: (lineId: number) => ["oee", lineId] as const,
  machineDowntime: (machineId: number) => ["machineDowntime", machineId] as const,
  /** Everything derived from downtime and its classification (refreshed after classifying). */
  downtime: ["downtime"] as const,
  downtimeAnalysis: (kind: string, params: unknown) => ["downtime", kind, params] as const,
  unclassified: (lineId: number) => ["downtime", "unclassified", lineId] as const,
  reasons: (factoryId: number, includeArchived = false) =>
    ["reasons", factoryId, includeArchived] as const,
  incident: (id: number) => ["incident", id] as const,
  /** Everything derived from inspection results and their reviews (refreshed after a review). */
  quality: ["quality"] as const,
  qualityAnalysis: (kind: string, params: unknown) => ["quality", kind, params] as const,
  shiftQuality: (lineId: number) => ["quality", "shift", lineId] as const,
  defectTypes: (includeArchived = false) => ["defectTypes", includeArchived] as const,
  stations: (lineId: number, includeArchived = false) => ["stations", lineId, includeArchived] as const,
  /** Everything about alerts (refreshed by alert messages and actions). */
  alerts: ["alerts"] as const,
  alertList: (params: unknown) => ["alerts", "list", params] as const,
  notifications: ["notifications"] as const,
  unreadCount: ["notifications", "unread"] as const,
  alertRules: (factoryId: number) => ["alertRules", factoryId] as const,
  ruleTypes: ["ruleTypes"] as const,
  preferences: ["preferences"] as const,
  health: ["health"] as const,
  /** Everything about maintenance actions (refreshed by maintenance_updated messages). */
  maintenance: ["maintenance"] as const,
  maintenanceList: (params: unknown) => ["maintenance", "list", params] as const,
  maintenanceAction: (id: number) => ["maintenance", "action", id] as const,
  myOpenActions: ["maintenance", "mine"] as const,
  /** The AI assistant. */
  assistantStatus: ["assistant", "status"] as const,
  assistantConversations: ["assistant", "conversations"] as const,
  assistantConversation: (id: number) => ["assistant", "conversation", id] as const,
};
