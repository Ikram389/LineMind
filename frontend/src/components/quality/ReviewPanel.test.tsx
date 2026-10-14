import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as quality from "../../api/quality.ts";
import type { QualityReview } from "../../api/qualityTypes.ts";
import { DEFECT_TYPES, makeResult } from "../../test/qualityFixtures.ts";
import { renderWithProviders } from "../../test/render.tsx";
import { ReviewPanel } from "./ReviewPanel.tsx";

const review = (overrides: Partial<QualityReview> = {}): QualityReview => ({
  id: 9, verdict: "confirmed", corrected_defect_type: null, comment: "",
  reviewed_by: "inspector@demo.test", reviewed_at: "2026-10-13T09:20:00Z", ...overrides,
});

beforeEach(() => {
  vi.spyOn(quality, "getReviews").mockResolvedValue([]);
  vi.spyOn(quality, "listDefectTypes").mockResolvedValue(DEFECT_TYPES);
});

function open(onSaved = vi.fn(), onClose = vi.fn()) {
  renderWithProviders(
    <ReviewPanel result={makeResult()} zone="UTC" canReview onClose={onClose} onSaved={onSaved} />,
    { role: "quality_inspector" },
  );
  return { onSaved, onClose };
}

describe("ReviewPanel", () => {
  it("confirms a defect", async () => {
    const save = vi.spyOn(quality, "reviewResult").mockResolvedValue(review());
    const { onSaved, onClose } = open();

    expect(screen.getByRole("button", { name: "Save review" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    fireEvent.click(screen.getByRole("button", { name: "Save review" }));

    await waitFor(() => expect(save).toHaveBeenCalledWith(51, "confirmed", null, ""));
    expect(onSaved).toHaveBeenCalledWith("Confirmed");
    expect(onClose).toHaveBeenCalled();
  });

  it("marks a false reject with a comment", async () => {
    const save = vi.spyOn(quality, "reviewResult").mockResolvedValue(review({ verdict: "false_reject" }));
    const { onSaved } = open();

    fireEvent.click(screen.getByRole("button", { name: "False reject" }));
    fireEvent.change(screen.getByLabelText("Comment (optional)"), { target: { value: "Glare on the label" } });
    fireEvent.click(screen.getByRole("button", { name: "Save review" }));

    await waitFor(() => expect(save).toHaveBeenCalledWith(51, "false_reject", null, "Glare on the label"));
    expect(onSaved).toHaveBeenCalledWith("False reject");
  });

  it("reclassifies to another defect type, which must be chosen first", async () => {
    const save = vi.spyOn(quality, "reviewResult").mockResolvedValue(
      review({ verdict: "reclassified", corrected_defect_type: { id: 3, code: "Q03", name: "Misaligned", severity: "minor" } }),
    );
    const { onSaved } = open();

    fireEvent.click(screen.getByRole("button", { name: "Reclassify" }));
    expect(screen.getByRole("button", { name: "Save review" })).toBeDisabled();
    // The detected type (Q02) is not offered.
    await screen.findByRole("button", { name: "Q03 · Misaligned or wrinkled label" });
    expect(screen.queryByRole("button", { name: "Q02 · Missing label" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Q03 · Misaligned or wrinkled label" }));
    fireEvent.click(screen.getByRole("button", { name: "Save review" }));

    await waitFor(() => expect(save).toHaveBeenCalledWith(51, "reclassified", 3, ""));
    expect(onSaved).toHaveBeenCalledWith("Reclassified as Q03");
  });

  it("shows the review history, newest first, and errors from the server", async () => {
    vi.spyOn(quality, "getReviews").mockResolvedValue([
      review({ id: 2, verdict: "false_reject", comment: "glare" }),
      review({ id: 1 }),
    ]);
    vi.spyOn(quality, "reviewResult").mockRejectedValue(new Error("Network down"));
    open();

    const history = await screen.findByTestId("review-history");
    expect(history.children[0]).toHaveTextContent("False reject by inspector@demo.test");
    expect(history.children[0]).toHaveTextContent("glare");
    expect(history.children[1]).toHaveTextContent("Confirmed");

    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    fireEvent.click(screen.getByRole("button", { name: "Save review" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Network down");
  });

  it("is read-only without the review permission", () => {
    renderWithProviders(<ReviewPanel result={makeResult()} zone="UTC" canReview={false} onClose={() => {}} />, {
      role: "machine_operator",
    });

    expect(screen.queryByRole("button", { name: "Confirm" })).toBeNull();
    expect(screen.getByText("Only quality inspectors, supervisors and managers can review defects.")).toBeInTheDocument();
  });
});
