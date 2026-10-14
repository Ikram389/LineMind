import { act, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import * as downtime from "../../api/downtime.ts";
import * as quality from "../../api/quality.ts";
import type { CurrentShift } from "../../api/types.ts";
import { applyLiveMessage } from "../../live/useLineLive.ts";
import { renderWithProviders } from "../../test/render.tsx";
import { LineNav } from "../LineNav.tsx";
import { QualityCard } from "./QualityCard.tsx";

const SHIFT: CurrentShift = {
  shift_id: 1, name: "Morning", label: "Morning 2026-10-13", local_date: "2026-10-13",
  start: "2026-10-13T05:00:00Z", end: "2026-10-13T13:00:00Z", breaks: [], factory_timezone: "Africa/Algiers",
};

describe("QualityCard", () => {
  it("shows the shift's quality and follows quality_updated messages", async () => {
    vi.spyOn(quality, "getShiftQuality").mockResolvedValue({
      shift: { label: SHIFT.label, start: SHIFT.start, end: SHIFT.end },
      defects: 12, defect_rate: 0.004, unreviewed: 10, total_count: 3000,
    });
    const { queryClient } = renderWithProviders(<QualityCard lineId={1} shift={SHIFT} />);

    expect(await screen.findByTestId("qcard-rate")).toHaveTextContent("0.40%");
    expect(screen.getByTestId("qcard-defects")).toHaveTextContent("12");
    expect(screen.getByRole("link", { name: "Open the quality page" })).toHaveAttribute("href", "/lines/1/quality");

    act(() =>
      applyLiveMessage(queryClient, 1, {
        type: "quality_updated",
        line_id: 1,
        sent_at: "2026-10-13T09:10:00Z",
        data: {
          shift: { label: SHIFT.label, start: SHIFT.start, end: SHIFT.end },
          defects: 13, defect_rate: 0.0043, unreviewed: 11, total_count: 3010,
        },
      }),
    );

    // TanStack Query tells components about cache changes on the next tick.
    await waitFor(() => expect(screen.getByTestId("qcard-defects")).toHaveTextContent("13"));
    expect(screen.getByTestId("qcard-rate")).toHaveTextContent("0.43%");
    expect(screen.getByTestId("qcard-unreviewed")).toHaveTextContent("11");
    expect(quality.getShiftQuality).toHaveBeenCalledTimes(1); // updated from the message, no refetch
  });

  it("says when no shift is running", async () => {
    vi.spyOn(quality, "getShiftQuality").mockResolvedValue({
      shift: null, defects: 0, defect_rate: null, unreviewed: 0, total_count: 0,
    });
    renderWithProviders(<QualityCard lineId={1} shift={null} />);

    expect(await screen.findByText("No shift running.")).toBeInTheDocument();
  });
});

describe("LineNav quality links", () => {
  it("shows Quality to everyone and Quality setup only to managers", () => {
    vi.spyOn(downtime, "countUnclassified").mockResolvedValue(0);
    const analyst = renderWithProviders(<LineNav lineId={1} shift={SHIFT} />, { role: "analyst" });
    expect(screen.getByRole("link", { name: "Quality" })).toHaveAttribute("href", "/lines/1/quality");
    expect(screen.queryByRole("link", { name: "Quality setup" })).toBeNull();
    analyst.unmount();

    renderWithProviders(<LineNav lineId={1} shift={SHIFT} />, { role: "factory_manager" });
    expect(screen.getByRole("link", { name: "Quality setup" })).toHaveAttribute("href", "/lines/1/quality-setup");
  });
});
