import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as alerts from "../api/alerts.ts";
import * as endpoints from "../api/endpoints.ts";
import { makeAlert } from "../test/alertFixtures.ts";
import { renderWithProviders } from "../test/render.tsx";
import { AlertsPage } from "./AlertsPage.tsx";

beforeEach(() => {
  vi.spyOn(endpoints, "listLines").mockResolvedValue([{ id: 1, factory: 1, name: "Bottling Line 1", counting_machine: null }]);
  vi.spyOn(alerts, "listAlerts").mockResolvedValue({
    count: 2,
    next: null,
    previous: null,
    results: [
      makeAlert(),
      makeAlert({
        id: 30, severity: "critical", status: "resolved", resolution: "auto", resolved_at: "2026-10-14T08:00:00Z",
        message_key: "alert.machine_offline", message_values: { machine: "Filler", minutes: 1 },
        subject: { type: "machine", id: 3, key: "machine:3:offline" }, machine: { id: 3, name: "Filler" },
      }),
    ],
  });
});

describe("AlertsPage", () => {
  it("reads its filters from the URL and changes them there", async () => {
    renderWithProviders(<AlertsPage />, { route: "/alerts?status=unresolved&severity=critical", path: "/alerts" });

    await screen.findByTestId("alert-31");
    expect(alerts.listAlerts).toHaveBeenCalledWith(expect.objectContaining({ status: "unresolved", severity: "critical" }));

    fireEvent.change(screen.getByLabelText("Type"), { target: { value: "machine_offline" } });
    await waitFor(() =>
      expect(alerts.listAlerts).toHaveBeenLastCalledWith(
        expect.objectContaining({ status: "unresolved", severity: "critical", type: "machine_offline" }),
      ),
    );
  });

  it("shows severity as colour, icon and text, and what happened", async () => {
    renderWithProviders(<AlertsPage />, { route: "/alerts", path: "/alerts" });

    const open = await screen.findByTestId("alert-31");
    expect(within(open).getByText(/Warning · Open/)).toBeInTheDocument();
    expect(within(open).getByRole("heading")).toHaveTextContent(
      "Line stopped for more than 1 min: first observed stop Labeler (alarm E-204)",
    );
    const resolved = screen.getByTestId("alert-30");
    expect(within(resolved).getByText(/Critical · Resolved/)).toBeInTheDocument();
    expect(within(resolved).getByText(/Resolved automatically/)).toBeInTheDocument();
    expect(within(resolved).getByRole("link", { name: "Open the machine" })).toHaveAttribute("href", "/lines/1/machines/3");
    expect(within(resolved).queryByRole("button", { name: /Acknowledge/ })).toBeNull();
  });

  it("acknowledges with a note", async () => {
    const ack = vi.spyOn(alerts, "acknowledgeAlert").mockResolvedValue(makeAlert({ status: "acknowledged" }));
    renderWithProviders(<AlertsPage />, { route: "/alerts", path: "/alerts" });

    const open = await screen.findByTestId("alert-31");
    fireEvent.change(within(open).getByLabelText("Note (optional)"), { target: { value: "On my way" } });
    fireEvent.click(within(open).getByRole("button", { name: "✓ Acknowledge" }));

    await waitFor(() => expect(ack).toHaveBeenCalledWith(31, "On my way"));
  });

  it("needs a note to resolve, and hides buttons people cannot use", async () => {
    const resolve = vi.spyOn(alerts, "resolveAlert").mockResolvedValue(makeAlert({ status: "resolved" }));
    const supervisor = renderWithProviders(<AlertsPage />, { route: "/alerts", path: "/alerts" });
    const open = await screen.findByTestId("alert-31");
    fireEvent.click(within(open).getByRole("button", { name: "Resolve…" }));
    const confirm = within(open).getByRole("button", { name: "Resolve" });
    expect(confirm).toBeDisabled();
    fireEvent.change(within(open).getByLabelText("Why is it resolved? (required)"), { target: { value: "Sensor cable fixed" } });
    fireEvent.click(confirm);
    await waitFor(() => expect(resolve).toHaveBeenCalledWith(31, "Sensor cable fixed"));
    supervisor.unmount();

    vi.spyOn(alerts, "listAlerts").mockResolvedValue({
      count: 1, next: null, previous: null, results: [makeAlert({ can_acknowledge: false })],
    });
    renderWithProviders(<AlertsPage />, { role: "analyst", route: "/alerts", path: "/alerts" });
    const readOnly = await screen.findByTestId("alert-31");
    expect(within(readOnly).queryByRole("button", { name: /Acknowledge/ })).toBeNull();
    expect(within(readOnly).queryByRole("button", { name: "Resolve…" })).toBeNull();
  });
});
