/** Downtime analysis, classification and reason management endpoints (build step 8). */
import type {
  AnalysedDowntimeEvent,
  IncidentDetail,
  ParetoResponse,
  Reason,
  ReasonCategory,
  RecurringResponse,
  ShiftOccurrence,
  SummaryResponse,
} from "./analysisTypes.ts";
import { apiDownload, apiFetch } from "./client.ts";
import type { Classification, CurrentShift, Paginated } from "./types.ts";

export interface LineMachine {
  id: number;
  line: number;
  external_id: string;
  name: string;
  position: number;
}

export const listLineMachines = (lineId: number): Promise<LineMachine[]> =>
  apiFetch(`/machines/?line=${lineId}`);

/** Stops of the current shift that still need a reason (count only, for the badge). */
export const countUnclassified = async (lineId: number, shift: CurrentShift): Promise<number> => {
  const page = await apiFetch<Paginated<unknown>>(
    `/downtime-events/?${toQueryString({
      line: lineId,
      start: shift.start,
      end: shift.end,
      needs_reason: true,
      classified: false,
      limit: 1,
    })}`,
  );
  return page.count;
};

/** Query parameters shared by the analysis endpoints, the events list and the CSV export. */
export type DowntimeQuery = Record<string, string | number | boolean | undefined | null>;

export function toQueryString(params: DowntimeQuery): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  }
  return search.toString();
}

export const getPareto = (params: DowntimeQuery): Promise<ParetoResponse> =>
  apiFetch(`/downtime/pareto/?${toQueryString(params)}`);

export const getDowntimeSummary = (params: DowntimeQuery): Promise<SummaryResponse> =>
  apiFetch(`/downtime/summary/?${toQueryString(params)}`);

export const getRecurring = (params: DowntimeQuery): Promise<RecurringResponse> =>
  apiFetch(`/downtime/recurring/?${toQueryString(params)}`);

export const listDowntimeEvents = (
  params: DowntimeQuery,
): Promise<Paginated<AnalysedDowntimeEvent>> =>
  apiFetch(`/downtime-events/?${toQueryString(params)}`);

export const exportDowntimeCsv = (params: DowntimeQuery): Promise<Blob> =>
  apiDownload(`/downtime-events/export.csv?${toQueryString(params)}`);

export const getIncident = (id: number): Promise<IncidentDetail> =>
  apiFetch(`/incidents/${id}/`);

export const getClassifications = (eventId: number): Promise<Classification[]> =>
  apiFetch(`/downtime-events/${eventId}/classifications/`);

export const classifyEvent = (
  eventId: number,
  reason: number,
  comment: string,
): Promise<Classification> =>
  apiFetch(`/downtime-events/${eventId}/classifications/`, {
    method: "POST",
    body: JSON.stringify({ reason, comment }),
  });

export const bulkClassify = (
  eventIds: number[],
  reason: number,
  comment: string,
): Promise<{ classified: number }> =>
  apiFetch("/downtime-events/bulk-classify/", {
    method: "POST",
    body: JSON.stringify({ event_ids: eventIds, reason, comment }),
  });

export const getSuggestedReasons = (eventId: number): Promise<Reason[]> =>
  apiFetch(`/downtime-events/${eventId}/suggested-reasons/`);

export const listReasons = (factoryId: number, includeArchived = false): Promise<Reason[]> =>
  apiFetch(
    `/downtime-reasons/?${toQueryString({ factory: factoryId, include_archived: includeArchived || undefined })}`,
  );

export interface ReasonInput {
  code: string;
  name: string;
  category: ReasonCategory;
  is_changeover: boolean;
}

export const createReason = (factoryId: number, input: ReasonInput): Promise<Reason> =>
  apiFetch("/downtime-reasons/", {
    method: "POST",
    body: JSON.stringify({ factory: factoryId, ...input }),
  });

export const updateReason = (id: number, input: Partial<ReasonInput>): Promise<Reason> =>
  apiFetch(`/downtime-reasons/${id}/`, { method: "PATCH", body: JSON.stringify(input) });

export const archiveReason = (id: number): Promise<Reason> =>
  apiFetch(`/downtime-reasons/${id}/archive/`, { method: "POST" });

export const restoreReason = (id: number): Promise<Reason> =>
  apiFetch(`/downtime-reasons/${id}/restore/`, { method: "POST" });

export const deleteReason = (id: number): Promise<null> =>
  apiFetch(`/downtime-reasons/${id}/`, { method: "DELETE" });

export const getShiftOccurrences = (
  factoryId: number,
  start: string,
  end: string,
): Promise<ShiftOccurrence[]> =>
  apiFetch(`/factories/${factoryId}/shift-occurrences/?${toQueryString({ start, end })}`);
