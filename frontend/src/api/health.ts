export type ServiceStatus = "ok" | "error";

export interface HealthResponse {
  status: ServiceStatus;
  database: ServiceStatus;
}

function isHealthResponse(value: unknown): value is HealthResponse {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const candidate = value as Record<string, unknown>;
  const isStatus = (v: unknown): v is ServiceStatus => v === "ok" || v === "error";
  return isStatus(candidate.status) && isStatus(candidate.database);
}

/**
 * Calls GET /api/v1/health/.
 * The backend answers 503 (with a JSON body) when the database is down,
 * so we read the body for any status code and only fail if it's not valid JSON.
 */
export async function fetchHealth(signal?: AbortSignal): Promise<HealthResponse> {
  const response = await fetch("/api/v1/health/", { signal });
  const body: unknown = await response.json();
  if (!isHealthResponse(body)) {
    throw new Error(`Unexpected health response (HTTP ${response.status})`);
  }
  return body;
}
