/**
 * The one place that talks HTTP to the backend.
 *
 * - The access token lives only in memory.
 * - DEVELOPMENT ONLY: the refresh token is kept in localStorage so a page reload
 *   keeps you logged in. Before production it moves to an httpOnly cookie set by
 *   the backend, out of reach of JavaScript.
 * - A 401 triggers one token refresh and one retry; if that fails, the user is
 *   logged out (never an endless loop).
 */
import { recordDateHeader } from "../lib/serverClock.ts";
import type { Tokens } from "./types.ts";

const REFRESH_KEY = "linemind.refreshToken";
const BASE = "/api/v1";

let accessToken: string | null = null;
let refreshing: Promise<boolean> | null = null;
const logoutListeners = new Set<() => void>();

export class ApiError extends Error {
  readonly status: number;
  readonly body: unknown;

  constructor(status: number, body: unknown) {
    super(`API request failed with status ${status}`);
    this.status = status;
    this.body = body;
  }
}

export function setTokens(tokens: Partial<Tokens>): void {
  if (tokens.access !== undefined) accessToken = tokens.access;
  if (tokens.refresh !== undefined) localStorage.setItem(REFRESH_KEY, tokens.refresh);
}

export function hasRefreshToken(): boolean {
  return localStorage.getItem(REFRESH_KEY) !== null;
}

export function clearTokens(): void {
  accessToken = null;
  localStorage.removeItem(REFRESH_KEY);
}

export function onLogout(listener: () => void): () => void {
  logoutListeners.add(listener);
  return () => logoutListeners.delete(listener);
}

function forceLogout(): void {
  clearTokens();
  logoutListeners.forEach((listener) => listener());
}

async function readBody(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return text;
  }
}

async function refreshAccessToken(): Promise<boolean> {
  const refresh = localStorage.getItem(REFRESH_KEY);
  if (!refresh) return false;
  const response = await fetch(`${BASE}/auth/token/refresh/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh }),
  });
  if (!response.ok) return false;
  const body = (await response.json()) as { access: string };
  accessToken = body.access;
  return true;
}

/** A request with the access token; one refresh and one retry on 401. */
async function authorizedRequest(path: string, init: RequestInit, retry: boolean): Promise<Response> {
  const headers = new Headers(init.headers);
  if (init.body !== undefined && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);

  const response = await fetch(`${BASE}${path}`, { ...init, headers });
  recordDateHeader(response.headers.get("Date"));

  if (response.status === 401) {
    if (retry) {
      // One refresh shared by all requests that failed at the same time.
      refreshing ??= refreshAccessToken().finally(() => {
        refreshing = null;
      });
      if (await refreshing) return authorizedRequest(path, init, false);
    }
    forceLogout();
    throw new ApiError(401, await readBody(response));
  }
  if (!response.ok) throw new ApiError(response.status, await readBody(response));
  return response;
}

export async function apiFetch<T>(path: string, init: RequestInit = {}, retry = true): Promise<T> {
  const response = await authorizedRequest(path, init, retry);
  return (await readBody(response)) as T;
}

/** Download a file (e.g. CSV) with the user's token; returns its contents. */
export async function apiDownload(path: string): Promise<Blob> {
  const response = await authorizedRequest(path, {}, true);
  return response.blob();
}

/** For tests. */
export function resetClientState(): void {
  accessToken = null;
  refreshing = null;
  logoutListeners.clear();
}
