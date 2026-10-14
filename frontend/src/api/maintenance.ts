/** Maintenance actions endpoints (build step 10b). */
import { apiDownload, apiFetch } from "./client.ts";
import { type DowntimeQuery, toQueryString } from "./downtime.ts";
import type {
  ActionInput,
  ActionLink,
  ActionStatus,
  Diagnosis,
  DiagnosisPreview,
  Effectiveness,
  LinkInput,
  MaintenanceAction,
  Part,
  Prefill,
  PrefillSource,
  StatusChange,
  WorkEntry,
} from "./maintenanceTypes.ts";
import type { Paginated } from "./types.ts";

const URL = "/maintenance-actions/";

export const listActions = (params: DowntimeQuery): Promise<Paginated<MaintenanceAction>> =>
  apiFetch(`${URL}?${toQueryString(params)}`);

export const getAction = (id: number): Promise<MaintenanceAction> => apiFetch(`${URL}${id}/`);

export const createAction = (input: ActionInput): Promise<MaintenanceAction> =>
  apiFetch(URL, { method: "POST", body: JSON.stringify(input) });

export const updateAction = (id: number, changes: Record<string, unknown>): Promise<MaintenanceAction> =>
  apiFetch(`${URL}${id}/`, { method: "PATCH", body: JSON.stringify(changes) });

export const transitionAction = (
  id: number,
  body: { to: ActionStatus; note?: string; assignee?: number | null; fixed_at?: string | null },
): Promise<MaintenanceAction> => apiFetch(`${URL}${id}/transition/`, { method: "POST", body: JSON.stringify(body) });

export const verifyAction = (
  id: number,
  result: "effective" | "not_effective",
  note: string,
): Promise<MaintenanceAction> => apiFetch(`${URL}${id}/verify/`, { method: "POST", body: JSON.stringify({ result, note }) });

export const listEntries = (id: number): Promise<WorkEntry[]> => apiFetch(`${URL}${id}/entries/`);

export const addEntry = (
  id: number,
  entry: { kind: WorkEntry["kind"]; text: string; time_spent_minutes: number; parts: Part[] },
): Promise<WorkEntry> => apiFetch(`${URL}${id}/entries/`, { method: "POST", body: JSON.stringify(entry) });

export const listLinks = (id: number): Promise<ActionLink[]> => apiFetch(`${URL}${id}/links/`);

export const addLinks = (id: number, links: LinkInput[]): Promise<ActionLink[]> =>
  apiFetch(`${URL}${id}/links/`, { method: "POST", body: JSON.stringify(links) });

export const getHistory = (id: number): Promise<{ status_changes: StatusChange[]; diagnoses: Diagnosis[] }> =>
  apiFetch(`${URL}${id}/history/`);

export const previewDiagnosis = (id: number, reason: number): Promise<DiagnosisPreview> =>
  apiFetch(`${URL}${id}/diagnosis/?reason=${reason}`);

export const recordDiagnosis = (
  id: number,
  body: { reason: number; text: string; apply_to_linked_stops: boolean; replace_other_reasons: boolean },
): Promise<Diagnosis> => apiFetch(`${URL}${id}/diagnosis/`, { method: "POST", body: JSON.stringify(body) });

export const getEffectiveness = (id: number): Promise<Effectiveness> => apiFetch(`${URL}${id}/effectiveness/`);

export const getPrefill = (source: PrefillSource): Promise<Prefill> =>
  apiFetch(`${URL}prefill/?${toQueryString(source)}`);

export const getMyOpenCount = async (): Promise<number> =>
  (await apiFetch<{ count: number }>(`${URL}mine/count/`)).count;

export const exportActionsCsv = (params: DowntimeQuery): Promise<Blob> =>
  apiDownload(`${URL}export.csv?${toQueryString(params)}`);

export const listAssignees = (id: number): Promise<{ id: number; email: string; role: string }[]> =>
  apiFetch(`${URL}${id}/assignees/`);
