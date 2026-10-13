/** Typed calls for every backend endpoint the dashboard uses. */
import { apiFetch, setTokens } from "./client.ts";
import type {
  CurrentShift,
  DowntimeEvent,
  Factory,
  Line,
  LineStatus,
  Me,
  OeeResponse,
  Paginated,
  Tokens,
} from "./types.ts";

export async function login(email: string, password: string): Promise<void> {
  const tokens = await apiFetch<Tokens>(
    "/auth/token/",
    { method: "POST", body: JSON.stringify({ email, password }) },
    false,
  );
  setTokens(tokens);
}

export const getMe = (): Promise<Me> => apiFetch<Me>("/me/");

export const listLines = (): Promise<Line[]> => apiFetch<Line[]>("/lines/");

export const getLine = (id: number): Promise<Line> => apiFetch<Line>(`/lines/${id}/`);

export const getFactory = (id: number): Promise<Factory> => apiFetch<Factory>(`/factories/${id}/`);

export const getLineStatus = (id: number): Promise<LineStatus> =>
  apiFetch<LineStatus>(`/lines/${id}/status/`);

export const getCurrentShift = (factoryId: number): Promise<CurrentShift | null> =>
  apiFetch<CurrentShift | null>(`/factories/${factoryId}/current-shift/`);

export function getOee(
  lineId: number,
  start: string,
  end: string,
  groupBy?: "hour" | "day" | "shift",
): Promise<OeeResponse> {
  const params = new URLSearchParams({ start, end });
  if (groupBy) params.set("group_by", groupBy);
  return apiFetch<OeeResponse>(`/lines/${lineId}/oee/?${params.toString()}`);
}

export function listMachineDowntime(
  machineId: number,
  start: string,
  end: string,
): Promise<Paginated<DowntimeEvent>> {
  const params = new URLSearchParams({ machine: String(machineId), start, end, limit: "500" });
  return apiFetch<Paginated<DowntimeEvent>>(`/downtime-events/?${params.toString()}`);
}

export const getWsTicket = (): Promise<{ ticket: string; expires_in: number }> =>
  apiFetch("/ws-ticket/", { method: "POST" });
