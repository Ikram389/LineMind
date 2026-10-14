import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as downtime from "../api/downtime.ts";
import * as endpoints from "../api/endpoints.ts";
import { ParetoPanel } from "../components/downtime/ParetoPanel.tsx";
import { REASONS, makeEvent, makePareto } from "../test/downtimeFixtures.ts";
import { renderWithProviders } from "../test/render.tsx";
import { DowntimePage } from "./DowntimePage.tsx";

beforeEach(() => {
  vi.spyOn(endpoints, "getLine").mockResolvedValue({ id: 1, factory: 1, name: "Bottling Line 1", counting_machine: null });
  vi.spyOn(endpoints, "getFactory").mockResolvedValue({
    id: 1, organization: 1, name: "Algiers Plant", timezone: "Africa/Algiers", stale_after_seconds: 60,
  });
  vi.spyOn(endpoints, "getCurrentShift").mockResolvedValue(null);
  vi.spyOn(downtime, "listLineMachines").mockResolvedValue([]);
  vi.spyOn(downtime, "listReasons").mockResolvedValue(REASONS);
  vi.spyOn(downtime, "getDowntimeSummary").mockResolvedValue({
    view: "line", view_note: "", total_seconds: 300, stops: 3, unclassified: 2, secondary_breakdowns: 0,
    longest: null, estimated_lost_units: { units: 500, is_estimate: true, basis: "" },
  });
  vi.spyOn(downtime, "getRecurring").mockResolvedValue({ threshold: 3, items: [] });
  vi.spyOn(downtime, "getPareto").mockResolvedValue(makePareto());
  vi.spyOn(downtime, "listDowntimeEvents").mockResolvedValue({ count: 1, next: null, previous: null, results: [makeEvent()] });
});

describe("ParetoPanel", () => {
  it("says which view it shows", () => {
    renderWithProviders(
      <ParetoPanel pareto={makePareto({ view: "machine", view_note: "Machine view: includes blocked and starved." })}
        groupBy="reason" onGroupBy={() => {}} onSelectGroup={() => {}} selectedKey={null} />,
    );

    expect(screen.getByTestId("pareto-view")).toHaveTextContent("MACHINE VIEW");
    expect(screen.getByText(/includes blocked and starved/)).toBeInTheDocument();
  });
});

describe("DowntimePage", () => {
  it("clicking a Pareto group filters the table (and the URL)", async () => {
    renderWithProviders(<DowntimePage />, { route: "/lines/1/downtime?start=2026-10-13T05:00:00Z&end=2026-10-13T13:00:00Z", path: "/lines/:lineId/downtime" });

    expect(await screen.findByTestId("pareto-view")).toHaveTextContent("LINE VIEW");
    fireEvent.click(await screen.findByTestId("pareto-group-unclassified"));

    await waitFor(() =>
      expect(downtime.listDowntimeEvents).toHaveBeenLastCalledWith(
        expect.objectContaining({ reason: "unclassified", line: 1, view: "line" }),
      ),
    );

    fireEvent.click(screen.getByTestId("pareto-group-reason:1"));
    await waitFor(() =>
      expect(downtime.listDowntimeEvents).toHaveBeenLastCalledWith(expect.objectContaining({ reason: "MECH-JAM" })),
    );
  });

  it("hides classification buttons for analysts and bulk selection for operators", async () => {
    const route = "/lines/1/downtime?start=2026-10-13T05:00:00Z&end=2026-10-13T13:00:00Z";
    const analyst = renderWithProviders(<DowntimePage />, { role: "analyst", route, path: "/lines/:lineId/downtime" });
    await screen.findByTestId("event-row-11");
    expect(screen.queryByRole("button", { name: "Classify" })).toBeNull();
    expect(screen.queryByRole("checkbox", { name: /Select/ })).toBeNull();
    analyst.unmount();

    renderWithProviders(<DowntimePage />, { role: "machine_operator", route, path: "/lines/:lineId/downtime" });
    await screen.findByTestId("event-row-11");
    expect(screen.getByRole("button", { name: "Classify" })).toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: /Select/ })).toBeNull();
    expect(screen.queryByRole("link", { name: "Reasons" })).toBeNull();
  });

  it("lets supervisors select several stops and classify them together", async () => {
    renderWithProviders(<DowntimePage />, {
      route: "/lines/1/downtime?start=2026-10-13T05:00:00Z&end=2026-10-13T13:00:00Z",
      path: "/lines/:lineId/downtime",
    });

    fireEvent.click(await screen.findByRole("checkbox", { name: /Select Labeler/ }));

    expect(screen.getByRole("button", { name: "Classify 1 selected" })).toBeInTheDocument();
  });
});
