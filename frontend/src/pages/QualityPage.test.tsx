import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as downtime from "../api/downtime.ts";
import * as endpoints from "../api/endpoints.ts";
import * as quality from "../api/quality.ts";
import { makeMember } from "../test/downtimeFixtures.ts";
import { DEFECT_TYPES, TREND, makeQualityPareto, makeResult, makeSummary } from "../test/qualityFixtures.ts";
import { renderWithProviders } from "../test/render.tsx";
import { QualityPage } from "./QualityPage.tsx";

const ROUTE = "/lines/1/quality?start=2026-10-13T05:00:00Z&end=2026-10-13T13:00:00Z";
const PATH = "/lines/:lineId/quality";

beforeEach(() => {
  vi.spyOn(endpoints, "getLine").mockResolvedValue({ id: 1, factory: 1, name: "Bottling Line 1", counting_machine: null });
  vi.spyOn(endpoints, "getFactory").mockResolvedValue({
    id: 1, organization: 1, name: "Algiers Plant", timezone: "Africa/Algiers", stale_after_seconds: 60,
  });
  vi.spyOn(endpoints, "getCurrentShift").mockResolvedValue(null);
  vi.spyOn(downtime, "countUnclassified").mockResolvedValue(0);
  vi.spyOn(quality, "listStations").mockResolvedValue([]);
  vi.spyOn(quality, "listDefectTypes").mockResolvedValue(DEFECT_TYPES);
  vi.spyOn(quality, "listProducts").mockResolvedValue([]);
  vi.spyOn(quality, "getQualitySummary").mockResolvedValue(makeSummary());
  vi.spyOn(quality, "getQualityPareto").mockResolvedValue(makeQualityPareto());
  vi.spyOn(quality, "getQualityTrend").mockResolvedValue(TREND);
  vi.spyOn(quality, "listInspectionResults").mockResolvedValue({
    count: 1, next: null, previous: null, results: [makeResult()],
  });
});

describe("QualityPage", () => {
  it("reads its filters from the URL and passes them to every query", async () => {
    renderWithProviders(<QualityPage />, { route: `${ROUTE}&severity=major&group=station&reviewed=false`, path: PATH });

    await screen.findByTestId("result-row-51");
    const expected = expect.objectContaining({
      line: 1, start: "2026-10-13T05:00:00Z", end: "2026-10-13T13:00:00Z", severity: "major",
    });
    expect(quality.getQualitySummary).toHaveBeenCalledWith(expected);
    expect(quality.getQualityPareto).toHaveBeenCalledWith(expect.objectContaining({ group_by: "station" }));
    expect(quality.listInspectionResults).toHaveBeenCalledWith(expect.objectContaining({ reviewed: "false", severity: "major" }));
    expect(screen.getByTestId("qpareto-group-station")).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("quality-rate")).toHaveTextContent("2.00%");
    expect(screen.getByTestId("qtrend-total")).toHaveTextContent("2.00% (120 defects / 6,000 bottles)");
  });

  it("clicking a Pareto bar filters the results table", async () => {
    renderWithProviders(<QualityPage />, { route: ROUTE, path: PATH });

    fireEvent.click(await screen.findByTestId("qpareto-bar-defect_type:2"));
    await waitFor(() =>
      expect(quality.listInspectionResults).toHaveBeenLastCalledWith(expect.objectContaining({ defect_type: "Q02" })),
    );

    fireEvent.click(screen.getByTestId("qpareto-bar-defect_type:none"));
    await waitFor(() =>
      expect(quality.listInspectionResults).toHaveBeenLastCalledWith(expect.objectContaining({ defect_type: "unknown" })),
    );
  });

  it("shows the production context and opens the line stop from it", async () => {
    vi.spyOn(downtime, "getIncident").mockResolvedValue({
      id: 14, line: { id: 1, name: "Bottling Line 1" }, started_at: "2026-10-13T09:05:00Z",
      ended_at: "2026-10-13T09:06:30Z", duration_seconds: 90, is_ongoing: false, origin: "machine_stop",
      events: [makeMember({ id: 11, role_in_incident: "first_observed_stop" })],
    });
    renderWithProviders(<QualityPage />, { route: ROUTE, path: PATH });

    const row = await screen.findByTestId("result-row-51");
    expect(within(row).getByText(/Labeler running · last alarm E-204/)).toBeInTheDocument();
    expect(within(row).getByText("W050")).toBeInTheDocument();
    const link = within(row).getByRole("button", { name: "Open line stop #14" });
    expect(link).toHaveTextContent("Occurred 2 min after incident #14 ended (first observed stop: Labeler, E-204)");
    expect(link.textContent).not.toMatch(/caus/i);

    fireEvent.click(link);
    expect(await screen.findByRole("dialog", { name: "Line stop #14" })).toBeInTheDocument();
    expect(downtime.getIncident).toHaveBeenCalledWith(14);
  });

  it("offers Review to inspectors and only Details to analysts", async () => {
    const analyst = renderWithProviders(<QualityPage />, { role: "analyst", route: ROUTE, path: PATH });
    const row = await screen.findByTestId("result-row-51");
    expect(within(row).queryByRole("button", { name: "Review" })).toBeNull();
    fireEvent.click(within(row).getByRole("button", { name: "Details" }));
    expect(await screen.findByText("Only quality inspectors, supervisors and managers can review defects.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "False reject" })).toBeNull();
    analyst.unmount();

    renderWithProviders(<QualityPage />, { role: "quality_inspector", route: ROUTE, path: PATH });
    const inspectorRow = await screen.findByTestId("result-row-51");
    expect(within(inspectorRow).getByRole("button", { name: "Review" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Quality setup" })).toBeNull();
  });
});
