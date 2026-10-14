import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as alerts from "../api/alerts.ts";
import * as downtime from "../api/downtime.ts";
import * as endpoints from "../api/endpoints.ts";
import * as maintenance from "../api/maintenance.ts";
import { AppBar } from "../components/AppBar.tsx";
import { IncidentDrawer } from "../components/downtime/IncidentDrawer.tsx";
import { makeMember } from "../test/downtimeFixtures.ts";
import { makeAction } from "../test/maintenanceFixtures.ts";
import { renderWithProviders } from "../test/render.tsx";
import { MaintenancePage } from "./MaintenancePage.tsx";

vi.mock("../live/useUserLive.ts", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../live/useUserLive.ts")>()),
  useUserLive: () => {},
}));

beforeEach(() => {
  vi.spyOn(endpoints, "listLines").mockResolvedValue([{ id: 1, factory: 1, name: "Bottling Line 1", counting_machine: null }]);
  vi.spyOn(maintenance, "listActions").mockResolvedValue({
    count: 2, next: null, previous: null,
    results: [makeAction({ is_overdue: true }), makeAction({ id: 14, title: "Cap torque", priority: "urgent", status: "assigned" })],
  });
});

describe("MaintenancePage", () => {
  it("opens on My actions for technicians and on all actions for supervisors", async () => {
    const technician = renderWithProviders(<MaintenancePage />, { role: "maintenance_technician", route: "/maintenance", path: "/maintenance" });
    await screen.findByTestId("action-12");
    expect(maintenance.listActions).toHaveBeenLastCalledWith(expect.objectContaining({ mine: "true", status: "open" }));
    expect(screen.getByRole("button", { name: "My actions" })).toHaveAttribute("aria-pressed", "true");
    technician.unmount();

    renderWithProviders(<MaintenancePage />, { role: "production_supervisor", route: "/maintenance", path: "/maintenance" });
    await screen.findByTestId("action-12");
    expect(maintenance.listActions).toHaveBeenLastCalledWith(expect.objectContaining({ mine: "" }));
  });

  it("shows overdue, priority and status with icons and text", async () => {
    renderWithProviders(<MaintenancePage />, { route: "/maintenance?status=open&overdue=true", path: "/maintenance" });

    const row = await screen.findByTestId("action-12");
    expect(row).toHaveTextContent("Overdue");
    expect(row).toHaveTextContent("High");
    expect(row).toHaveTextContent("In progress");
    expect(screen.getByTestId("action-14")).toHaveTextContent("Urgent");
    expect(maintenance.listActions).toHaveBeenLastCalledWith(expect.objectContaining({ overdue: "true" }));
  });
});

describe("Create action from a line stop", () => {
  it("pre-fills the machine and the links, then creates the request", async () => {
    vi.spyOn(downtime, "getIncident").mockResolvedValue({
      id: 14, line: { id: 1, name: "Bottling Line 1" }, started_at: "2026-10-13T09:05:00Z",
      ended_at: "2026-10-13T09:06:30Z", duration_seconds: 90, is_ongoing: false, origin: "machine_stop",
      events: [makeMember({ id: 11, role_in_incident: "first_observed_stop" })],
    });
    const prefill = vi.spyOn(maintenance, "getPrefill").mockResolvedValue({
      machine: 5, machine_name: "Labeler", line: 1, line_name: "Bottling Line 1",
      title: "Labeler: line stop #14 (E-204)", problem: "Line stop #14, first observed stop Labeler (E-204).",
      links: [{ kind: "incident", id: 14 }, { kind: "downtime_event", id: 11 }, { kind: "signature", machine: 5, alarm_code: "E-204" }],
    });
    const create = vi.spyOn(maintenance, "createAction").mockResolvedValue(makeAction({ id: 30, status: "requested" }));
    renderWithProviders(<IncidentDrawer incidentId={14} zone="UTC" onClose={() => {}} />, { role: "machine_operator" });

    fireEvent.click(await screen.findByRole("button", { name: "Create action" }));
    expect(await screen.findByTestId("new-action-machine")).toHaveTextContent("Machine: Labeler (Bottling Line 1)");
    expect(prefill).toHaveBeenCalledWith({ source: "incident", id: 14 });
    expect(screen.getByLabelText("Title")).toHaveValue("Labeler: line stop #14 (E-204)");
    expect(screen.getByTestId("new-action-links")).toHaveTextContent("the recurring problem, 1 stops, 1 other records");
    fireEvent.click(screen.getByRole("button", { name: "Create request" }));

    await waitFor(() =>
      expect(create).toHaveBeenCalledWith(
        expect.objectContaining({
          machine: 5,
          action_type: "corrective",
          links: [{ kind: "incident", id: 14 }, { kind: "downtime_event", id: 11 }, { kind: "signature", machine: 5, alarm_code: "E-204" }],
        }),
      ),
    );
  });

  it("is not offered to analysts", async () => {
    vi.spyOn(downtime, "getIncident").mockResolvedValue({
      id: 14, line: { id: 1, name: "Bottling Line 1" }, started_at: "2026-10-13T09:05:00Z", ended_at: null,
      duration_seconds: 90, is_ongoing: true, origin: "machine_stop", events: [],
    });
    renderWithProviders(<IncidentDrawer incidentId={14} zone="UTC" onClose={() => {}} />, { role: "analyst" });

    await screen.findByRole("dialog");
    expect(screen.queryByRole("button", { name: "Create action" })).toBeNull();
  });
});

describe("Top bar badge", () => {
  it("counts my open assigned actions", async () => {
    vi.spyOn(alerts, "getUnreadCount").mockResolvedValue(0);
    vi.spyOn(alerts, "listAlerts").mockResolvedValue({ count: 0, next: null, previous: null, results: [] });
    vi.spyOn(alerts, "getHealth").mockResolvedValue({ status: "ok", database: "ok", alerts: "ok" });
    vi.spyOn(maintenance, "getMyOpenCount").mockResolvedValue(2);
    renderWithProviders(<AppBar />, { role: "maintenance_technician" });

    const badge = await screen.findByTestId("my-actions-badge");
    expect(badge).toHaveTextContent("2");
    expect(badge).toHaveAttribute("href", "/maintenance?mine=true");
  });
});
