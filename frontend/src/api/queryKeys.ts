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
};
