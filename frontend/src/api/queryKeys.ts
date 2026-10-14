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
};
