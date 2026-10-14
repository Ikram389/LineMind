import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as alerts from "../api/alerts.ts";
import { applyUserMessage } from "../live/useUserLive.ts";
import { makeAlert } from "../test/alertFixtures.ts";
import { renderWithProviders } from "../test/render.tsx";
import { AppBar } from "./AppBar.tsx";

vi.mock("../live/useUserLive.ts", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../live/useUserLive.ts")>()),
  useUserLive: () => {}, // no real socket in tests; messages are applied by hand
}));

beforeEach(() => {
  vi.spyOn(alerts, "getUnreadCount").mockResolvedValue(2);
  vi.spyOn(alerts, "listAlerts").mockResolvedValue({ count: 1, next: null, previous: null, results: [makeAlert()] });
  vi.spyOn(alerts, "getHealth").mockResolvedValue({ status: "ok", database: "ok", alerts: "ok", alerts_last_heartbeat: null });
  vi.spyOn(alerts, "listNotifications").mockResolvedValue({
    count: 1,
    next: null,
    previous: null,
    results: [{ id: 7, alert: makeAlert(), channel: "in_app", reason: "opened", status: "sent", read_at: null, created_at: "2026-10-14T09:06:00Z" }],
  });
});

describe("AppBar", () => {
  it("shows the unread count and updates it from a live message", async () => {
    const { queryClient } = renderWithProviders(<AppBar />);

    expect(await screen.findByTestId("bell-count")).toHaveTextContent("2");
    expect(screen.getByRole("link", { name: "Alerts (1 open)" })).toBeInTheDocument();

    act(() =>
      applyUserMessage(queryClient, {
        type: "notifications_changed", line_id: 0, sent_at: "2026-10-14T09:07:00Z", data: { unread_count: 3 },
      }),
    );
    await waitFor(() => expect(screen.getByTestId("bell-count")).toHaveTextContent("3"));
  });

  it("lists the latest notifications and marks them all read", async () => {
    const readAll = vi.spyOn(alerts, "markAllNotificationsRead").mockResolvedValue({ unread_count: 0 });
    renderWithProviders(<AppBar />);

    fireEvent.click(await screen.findByRole("button", { name: "Notifications, 2 unread" }));
    expect(
      await screen.findByText("Line stopped for more than 1 min: first observed stop Labeler (alarm E-204)"),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Mark all read" }));

    await waitFor(() => expect(readAll).toHaveBeenCalled());
    await waitFor(() => expect(screen.queryByTestId("bell-count")).toBeNull());
  });

  it("warns supervisors when the alert engine is stale, but not operators", async () => {
    vi.spyOn(alerts, "getHealth").mockResolvedValue({
      status: "ok", database: "ok", alerts: "stale", alerts_last_heartbeat: "2026-10-14T09:42:00Z",
    });
    const supervisor = renderWithProviders(<AppBar />, { role: "production_supervisor" });
    expect(await screen.findByTestId("engine-stale")).toHaveTextContent(/Alerts are not being checked since \d\d:42/);
    supervisor.unmount();

    renderWithProviders(<AppBar />, { role: "machine_operator" });
    await screen.findByTestId("bell-count");
    expect(screen.queryByTestId("engine-stale")).toBeNull();
    expect(screen.queryByRole("link", { name: "Alert rules" })).toBeNull();
  });
});
