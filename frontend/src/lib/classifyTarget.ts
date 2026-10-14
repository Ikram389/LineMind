import type { DowntimeCategory } from "../api/types.ts";

/** The minimum the classification UI needs to know about a stop. */
export interface ClassifyTarget {
  id: number;
  machine: { id: number; name: string };
  category: DowntimeCategory;
  started_at: string;
  duration_seconds: number;
  alarm_code: string | null;
  role_in_incident?: string | null;
}
