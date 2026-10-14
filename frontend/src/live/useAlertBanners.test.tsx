import { act, fireEvent, renderHook, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import * as alerts from "../api/alerts.ts";
import type { AlertChanged, AlertSummary } from "../api/types.ts";
import { AlertBanner } from "../components/alerts/AlertBanner.tsx";
import { makeAlert } from "../test/alertFixtures.ts";
import { renderWithProviders } from "../test/render.tsx";
import { useAlertBanners } from "./useAlertBanners.ts";

function summary(overrides: Partial<AlertSummary> = {}): AlertSummary {
  return {
    alert_id: 31, rule_type: "long_stop", severity: "warning", status: "open", line_id: 1, machine_id: 5,
    subject_type: "incident", subject_id: 14, opened_at: "2026-10-14T09:06:00Z",
    condition_since: "2026-10-14T09:05:00Z", message_key: "alert.long_stop",
    message_values: { machine: "Labeler", minutes: 1, alarm: "E-204" },
    acknowledged_at: null, resolved_at: null, resolution: "", ...overrides,
  };
}

const message = (type: AlertChanged["type"], data: AlertSummary): AlertChanged => ({
  type, line_id: data.line_id ?? 0, sent_at: "2026-10-14T09:06:00Z", data,
});

describe("overview alert banners", () => {
  it("shows warning and critical alerts of this line only, until they resolve", () => {
    const { result } = renderHook(() => useAlertBanners(1));

    act(() => {
      result.current.onMessage(message("alert_opened", summary()));
      result.current.onMessage(message("alert_opened", summary({ alert_id: 32, line_id: 2 })));
      result.current.onMessage(message("alert_opened", summary({ alert_id: 33, severity: "info" })));
      result.current.onMessage(message("alert_opened", summary())); // the same alert again
    });
    expect(result.current.banners.map((b) => b.alert_id)).toEqual([31]);

    act(() => result.current.onMessage(message("alert_resolved", summary({ status: "resolved" }))));
    expect(result.current.banners).toEqual([]);
  });

  it("acknowledges from the banner", async () => {
    vi.spyOn(alerts, "getAlert").mockResolvedValue(makeAlert());
    const ack = vi.spyOn(alerts, "acknowledgeAlert").mockResolvedValue(makeAlert({ status: "acknowledged" }));
    renderWithProviders(<AlertBanner alert={summary()} zone="Africa/Algiers" onHide={() => {}} />);

    expect(screen.getByTestId("alert-banner")).toHaveTextContent(
      "Warning: Line stopped for more than 1 min: first observed stop Labeler (alarm E-204) — since 10:05",
    );
    fireEvent.click(await screen.findByRole("button", { name: "✓ Acknowledge" }));

    await waitFor(() => expect(ack).toHaveBeenCalledWith(31, ""));
    expect(await screen.findByText(/Acknowledged/)).toBeInTheDocument();
  });

  it("offers no Acknowledge button to people who cannot acknowledge", async () => {
    vi.spyOn(alerts, "getAlert").mockResolvedValue(makeAlert({ can_acknowledge: false }));
    renderWithProviders(<AlertBanner alert={summary()} zone="UTC" onHide={() => {}} />, { role: "analyst" });

    await waitFor(() => expect(alerts.getAlert).toHaveBeenCalled());
    expect(screen.queryByRole("button", { name: "✓ Acknowledge" })).toBeNull();
    expect(screen.getByRole("button", { name: "Hide" })).toBeInTheDocument();
  });
});
