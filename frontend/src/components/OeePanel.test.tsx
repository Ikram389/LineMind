import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { OeeResult } from "../api/types.ts";
import { OeePanel } from "./OeePanel.tsx";

const ratio = (percent: number) => ({ ratio: percent / 100, percent });

function result(overrides: Partial<OeeResult> = {}): OeeResult {
  return {
    availability: ratio(91.67),
    performance: ratio(100),
    quality: ratio(97),
    oee: ratio(88.92),
    data_coverage: ratio(100),
    null_reason: null,
    warnings: [],
    inputs: {},
    ...overrides,
  };
}

describe("OeePanel", () => {
  it("shows the four results and data coverage", () => {
    render(<OeePanel result={result()} />);

    expect(screen.getByText("88.9%")).toBeInTheDocument();
    expect(screen.getByText("91.7%")).toBeInTheDocument();
    expect(screen.getByText("100.0%")).toBeInTheDocument();
    expect(screen.getByText("97.0%")).toBeInTheDocument();
    expect(screen.getByText(/Data coverage/)).toHaveTextContent("Data coverage: 100%");
  });

  it("shows API warnings as readable messages", () => {
    render(
      <OeePanel
        result={result({
          warnings: [
            { code: "performance_above_100", message: "Performance is 150.0%: more was produced than the ideal cycle time allows." },
            { code: "low_data_coverage", message: "Only 83.33% of planned time has data from the counting machine." },
          ],
        })}
      />,
    );

    const list = screen.getByRole("list", { name: "Notes" });
    expect(list).toHaveTextContent("Performance is 150.0%");
    expect(list).toHaveTextContent("Only 83.33% of planned time has data");
    expect(screen.queryByText("performance_above_100")).toBeNull(); // codes are not shown
  });

  it("shows a dash and the reason when a result cannot be calculated", () => {
    render(
      <OeePanel
        result={result({
          performance: { ratio: null, percent: null, null_reason: "no run time: the line never ran" },
          oee: ratio(0),
        })}
      />,
    );

    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.getByText("no run time: the line never ran")).toBeInTheDocument();
  });
});
