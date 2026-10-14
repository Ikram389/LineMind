import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as downtime from "../api/downtime.ts";
import * as maintenance from "../api/maintenance.ts";
import { EffectivenessPanel } from "../components/maintenance/EffectivenessPanel.tsx";
import { REASONS } from "../test/downtimeFixtures.ts";
import { makeAction, makeEffect } from "../test/maintenanceFixtures.ts";
import { renderWithProviders } from "../test/render.tsx";
import { MaintenanceActionPage } from "./MaintenanceActionPage.tsx";

const ROUTE = { route: "/maintenance/12", path: "/maintenance/:actionId" };

beforeEach(() => {
  vi.spyOn(maintenance, "getAction").mockResolvedValue(makeAction());
  vi.spyOn(maintenance, "listLinks").mockResolvedValue([]);
  vi.spyOn(maintenance, "getHistory").mockResolvedValue({ status_changes: [], diagnoses: [] });
  vi.spyOn(maintenance, "getEffectiveness").mockResolvedValue(makeEffect({ status: "not_fixed", before: undefined, after: undefined, message_key: undefined }));
  vi.spyOn(maintenance, "listEntries").mockResolvedValue([]);
  vi.spyOn(downtime, "listReasons").mockResolvedValue(REASONS);
});

describe("MaintenanceActionPage", () => {
  it("shows only the steps the backend allows, and asks for a note when needed", async () => {
    const step = vi.spyOn(maintenance, "transitionAction").mockResolvedValue(makeAction({ status: "waiting" }));
    renderWithProviders(<MaintenanceActionPage />, { role: "maintenance_technician", ...ROUTE });

    const next = await screen.findByTestId("next-steps");
    expect(within(next).getAllByRole("button").map((b) => b.textContent)).toEqual(["Waiting…", "Complete…"]);

    fireEvent.click(within(next).getByRole("button", { name: "Waiting…" }));
    const confirm = screen.getByRole("button", { name: "Confirm" });
    expect(confirm).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Note (required)"), { target: { value: "Waiting for a roller" } });
    fireEvent.click(confirm);

    await waitFor(() =>
      expect(step).toHaveBeenCalledWith(12, expect.objectContaining({ to: "waiting", note: "Waiting for a roller" })),
    );
  });

  it("shows no step buttons to people who cannot act", async () => {
    vi.spyOn(maintenance, "getAction").mockResolvedValue(makeAction({ allowed_steps: [] }));
    renderWithProviders(<MaintenanceActionPage />, { role: "analyst", ...ROUTE });

    expect(await screen.findByText("Nothing for you to do on this action now.")).toBeInTheDocument();
    expect(within(screen.getByTestId("next-steps")).queryAllByRole("button")).toHaveLength(0);
    expect(screen.queryByRole("button", { name: "Add entry" })).toBeNull();
  });

  it("logs work with time and parts", async () => {
    const add = vi.spyOn(maintenance, "addEntry").mockResolvedValue({
      id: 1, kind: "repair", text: "Replaced the roller", time_spent_minutes: 45, parts: [{ name: "Roller", quantity: 1 }],
      author: { id: 9, email: "maintenance_technician@demo.test" }, created_at: "2026-10-14T09:00:00Z",
    });
    renderWithProviders(<MaintenanceActionPage />, { role: "maintenance_technician", ...ROUTE });

    fireEvent.click(await screen.findByRole("button", { name: "Repair done" }));
    fireEvent.change(screen.getByLabelText("What did you find or do?"), { target: { value: "Replaced the roller" } });
    fireEvent.change(screen.getByLabelText("Time spent (minutes)"), { target: { value: "45" } });
    fireEvent.click(screen.getByRole("button", { name: "+ Part" }));
    fireEvent.change(screen.getByLabelText("Part"), { target: { value: "Roller" } });
    fireEvent.click(screen.getByRole("button", { name: "Add entry" }));

    await waitFor(() =>
      expect(add).toHaveBeenCalledWith(12, {
        kind: "repair", text: "Replaced the roller", time_spent_minutes: 45, parts: [{ name: "Roller", quantity: 1 }],
      }),
    );
  });

  it("previews a diagnosis and applies it, replacing other reasons only when ticked", async () => {
    vi.spyOn(maintenance, "previewDiagnosis").mockResolvedValue({
      linked_stops: 165, unclassified: 150, same_reason: 5, same_category: 6,
      other_reasons: [{ code: "MAT-LABEL", name: "Label roll empty", count: 4 }],
      would_apply: 156, would_apply_with_replace: 160,
    });
    const save = vi.spyOn(maintenance, "recordDiagnosis").mockResolvedValue({
      id: 1, reason: { id: 1, code: "MECH-JAM", name: "Jam / blockage" }, text: "Worn roller", applied_to_stops: true,
      replace_other_reasons: false, applied_count: 156, skipped_count: 9,
      created_by: { id: 9, email: "maintenance_technician@demo.test" }, created_at: "2026-10-14T09:00:00Z",
    });
    renderWithProviders(<MaintenanceActionPage />, { role: "maintenance_technician", ...ROUTE });

    const form = await screen.findByRole("form", { name: "Confirmed diagnosis" });
    await waitFor(() => expect(within(form).getAllByRole("option").length).toBeGreaterThan(1));
    fireEvent.change(within(form).getByLabelText("Reason"), { target: { value: "1" } });
    fireEvent.change(within(form).getByLabelText("What was found"), { target: { value: "Worn roller" } });
    const preview = await screen.findByTestId("diagnosis-preview");
    expect(preview).toHaveTextContent("165 linked stops: 150 unclassified, 5 already this reason, 6 with another reason");
    expect(preview).toHaveTextContent("Label roll empty (4)");
    expect(preview).toHaveTextContent("Will classify 156 stops.");
    fireEvent.click(within(preview).getByLabelText(/Also replace reasons/));
    expect(preview).toHaveTextContent("Will classify 160 stops.");
    fireEvent.click(within(preview).getByLabelText(/Also replace reasons/)); // back to the default
    fireEvent.click(within(form).getByRole("button", { name: "Save diagnosis" }));

    await waitFor(() =>
      expect(save).toHaveBeenCalledWith(12, { reason: 1, text: "Worn roller", apply_to_linked_stops: true, replace_other_reasons: false }),
    );
    expect(await screen.findByText("Diagnosis saved: 156 stops classified, 9 left as they were.")).toBeInTheDocument();
  });
});

describe("EffectivenessPanel", () => {
  const action = makeAction({ status: "done" });

  it.each([
    ["improved", "Improved", "fell from 12 to 1.18"],
    ["no_change", "No clear change", "went from 12 to 11"],
    ["worse", "Worse", "rose from 12 to 20"],
  ] as const)("shows %s with the numbers", (status, label, text) => {
    const key = { improved: "effect.fell", no_change: "effect.similar", worse: "effect.rose" }[status];
    const to = { improved: 1.18, no_change: 11, worse: 20 }[status];
    renderWithProviders(
      <EffectivenessPanel effect={makeEffect({ status, message_key: key, message_values: { from: 12, to } })} action={action} canVerify={false} />,
    );

    expect(screen.getByTestId("effect-status")).toHaveTextContent(label);
    expect(screen.getByTestId("effect-message")).toHaveTextContent(text);
    expect(screen.getByText(/does not prove the repair caused the change/)).toBeInTheDocument();
  });

  it("says what is missing when there is not enough data", () => {
    renderWithProviders(
      <EffectivenessPanel
        effect={makeEffect({ status: "not_enough_data", reason: "after_run_time", missing_run_hours: 12.5, message_key: undefined })}
        action={action}
        canVerify={false}
      />,
    );
    expect(screen.getByTestId("effect-status")).toHaveTextContent("Not enough data yet");
    expect(screen.getByTestId("effect-reason")).toHaveTextContent("12.5 more run hours are needed after the fix.");
  });

  it("says when there were too few stops before the fix", () => {
    renderWithProviders(
      <EffectivenessPanel
        effect={makeEffect({ status: "not_enough_data", reason: "few_occurrences_before", message_key: undefined })}
        action={action}
        canVerify={false}
      />,
    );
    expect(screen.getByTestId("effect-reason")).toHaveTextContent("Too few occurrences before the fix (fewer than 5)");
  });

  it("lets supervisors verify a done action", async () => {
    const verify = vi.spyOn(maintenance, "verifyAction").mockResolvedValue(makeAction({ status: "verified" }));
    renderWithProviders(<EffectivenessPanel effect={makeEffect()} action={action} canVerify />, { role: "production_supervisor" });

    fireEvent.click(screen.getByRole("button", { name: "✓ Verify: effective" }));

    await waitFor(() => expect(verify).toHaveBeenCalledWith(12, "effective", ""));
  });
});
