import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as downtime from "../api/downtime.ts";
import { REASONS, makeEvent } from "../test/downtimeFixtures.ts";
import { renderWithProviders } from "../test/render.tsx";
import { ClassifyPanel } from "./ClassifyPanel.tsx";

beforeEach(() => {
  vi.spyOn(downtime, "listReasons").mockResolvedValue(REASONS);
  vi.spyOn(downtime, "getSuggestedReasons").mockResolvedValue(REASONS.slice(2, 3));
  vi.spyOn(downtime, "getClassifications").mockResolvedValue([]);
});

describe("ClassifyPanel", () => {
  it("lists the reasons that fit the stop's category first", async () => {
    renderWithProviders(
      <ClassifyPanel events={[makeEvent({ category: "starved" })]} factoryId={1} zone="Africa/Algiers" onClose={() => {}} />,
    );

    await screen.findByTestId("reason-group-material");
    const groups = screen.getAllByTestId(/^reason-group-/).map((el) => el.dataset.testid);
    expect(groups.slice(0, 2)).toEqual(["reason-group-material", "reason-group-organizational"]);
  });

  it("puts mechanical and electrical first for a breakdown, and searches", async () => {
    renderWithProviders(
      <ClassifyPanel events={[makeEvent({ category: "breakdown" })]} factoryId={1} zone="Africa/Algiers" onClose={() => {}} />,
    );

    await screen.findByTestId("reason-group-mechanical");
    expect(screen.getAllByTestId(/^reason-group-/)[0]).toHaveAttribute("data-testid", "reason-group-mechanical");

    fireEvent.change(screen.getByLabelText("Search reasons"), { target: { value: "sensor" } });
    expect(screen.getAllByTestId(/^reason-group-/).map((el) => el.dataset.testid)).toEqual([
      "reason-group-electrical",
    ]);
  });

  it("saves the chosen reason with a comment", async () => {
    const classify = vi.spyOn(downtime, "classifyEvent").mockResolvedValue({
      id: 1, reason: { id: 1, code: "MECH-JAM", name: "Jam / blockage", category: "mechanical" },
      comment: "Web snapped", source: "operator", created_by: "op@demo.test", created_at: "2026-10-13T09:10:00Z",
    });
    const onSaved = vi.fn();
    renderWithProviders(
      <ClassifyPanel events={[makeEvent({ id: 11 })]} factoryId={1} zone="Africa/Algiers" onClose={() => {}} onSaved={onSaved} />,
    );

    fireEvent.click(await screen.findByRole("button", { name: "Jam / blockage (MECH-JAM)" }));
    fireEvent.change(screen.getByLabelText("Comment (optional)"), { target: { value: "Web snapped" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(classify).toHaveBeenCalledWith(11, 1, "Web snapped"));
    expect(onSaved).toHaveBeenCalledWith("Jam / blockage");
  });

  it("classifies several stops at once in bulk mode", async () => {
    const bulk = vi.spyOn(downtime, "bulkClassify").mockResolvedValue({ classified: 2 });
    renderWithProviders(
      <ClassifyPanel events={[makeEvent({ id: 11 }), makeEvent({ id: 12 })]} factoryId={1} zone="UTC" onClose={() => {}} />,
    );

    expect(screen.getByText("One reason for 2 stops")).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: "Sensor fault (ELEC-SENSOR)" }));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(bulk).toHaveBeenCalledWith([11, 12], 2, ""));
  });
});
