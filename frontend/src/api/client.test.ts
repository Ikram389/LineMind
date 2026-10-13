import { describe, expect, it, vi } from "vitest";

import { ApiError, apiFetch, hasRefreshToken, onLogout, setTokens } from "./client.ts";

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

describe("apiFetch token refresh", () => {
  it("refreshes the access token once and retries the failed request", async () => {
    setTokens({ access: "expired", refresh: "refresh-1" });
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(json(401, { detail: "expired" })) // original request
      .mockResolvedValueOnce(json(200, { access: "fresh" })) // refresh
      .mockResolvedValueOnce(json(200, { ok: true })); // retry

    await expect(apiFetch<{ ok: boolean }>("/me/")).resolves.toEqual({ ok: true });

    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(fetchMock.mock.calls[1]?.[0]).toBe("/api/v1/auth/token/refresh/");
    const retryHeaders = new Headers(fetchMock.mock.calls[2]?.[1]?.headers);
    expect(retryHeaders.get("Authorization")).toBe("Bearer fresh");
  });

  it("logs out when the retry is refused again, without looping", async () => {
    setTokens({ access: "expired", refresh: "refresh-1" });
    const loggedOut = vi.fn();
    onLogout(loggedOut);
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(json(401, {}))
      .mockResolvedValueOnce(json(200, { access: "fresh" }))
      .mockResolvedValueOnce(json(401, {}));

    await expect(apiFetch("/me/")).rejects.toBeInstanceOf(ApiError);

    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(loggedOut).toHaveBeenCalledOnce();
    expect(hasRefreshToken()).toBe(false);
  });

  it("logs out when the refresh itself fails", async () => {
    setTokens({ access: "expired", refresh: "refresh-1" });
    const loggedOut = vi.fn();
    onLogout(loggedOut);
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(json(401, {}))
      .mockResolvedValueOnce(json(401, { detail: "refresh expired" }));

    await expect(apiFetch("/me/")).rejects.toMatchObject({ status: 401 });
    expect(loggedOut).toHaveBeenCalledOnce();
  });
});
