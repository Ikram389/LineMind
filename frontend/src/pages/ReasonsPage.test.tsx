import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as downtime from "../api/downtime.ts";
import * as endpoints from "../api/endpoints.ts";
import { makeReason } from "../test/downtimeFixtures.ts";
import { renderWithProviders } from "../test/render.tsx";
import { ReasonsPage } from "./ReasonsPage.tsx";

const ROUTE = { route: "/lines/1/reasons", path: "/lines/:lineId/reasons" };

beforeEach(() => {
  vi.spyOn(endpoints, "getLine").mockResolvedValue({ id: 1, factory: 1, name: "Bottling Line 1", counting_machine: null });
  vi.spyOn(endpoints, "getFactory").mockResolvedValue({
    id: 1, organization: 1, name: "Algiers Plant", timezone: "Africa/Algiers", stale_after_seconds: 60,
  });
  vi.spyOn(endpoints, "getCurrentShift").mockResolvedValue(null);
  vi.spyOn(downtime, "listReasons").mockResolvedValue([
    makeReason({ id: 1, code: "MECH-JAM", name: "Jam / blockage", in_use: true }),
    makeReason({ id: 2, code: "MECH-WEAR", name: "Worn part", in_use: false }),
  ]);
});

describe("ReasonsPage", () => {
  it("offers Delete only for reasons never used", async () => {
    renderWithProviders(<ReasonsPage />, { role: "factory_manager", ...ROUTE });

    const used = await screen.findByTestId("reason-MECH-JAM");
    const unused = screen.getByTestId("reason-MECH-WEAR");
    expect(within(used).queryByRole("button", { name: "Delete" })).toBeNull();
    expect(within(used).getByText(/can be archived, not deleted/)).toBeInTheDocument();
    expect(within(unused).getByRole("button", { name: "Delete" })).toBeInTheDocument();
  });

  it("creates and archives reasons", async () => {
    const create = vi.spyOn(downtime, "createReason").mockResolvedValue(makeReason({ id: 3, code: "MECH-BELT" }));
    const archive = vi.spyOn(downtime, "archiveReason").mockResolvedValue(makeReason({ id: 2, is_active: false }));
    renderWithProviders(<ReasonsPage />, { role: "factory_manager", ...ROUTE });

    fireEvent.click(await screen.findByRole("button", { name: "+ New reason" }));
    fireEvent.change(screen.getByLabelText("Code"), { target: { value: "MECH-BELT" } });
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Belt slipping" } });
    fireEvent.click(screen.getByLabelText("Changeover"));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(create).toHaveBeenCalledWith(1, {
        code: "MECH-BELT", name: "Belt slipping", category: "mechanical", is_changeover: true,
      }),
    );

    fireEvent.click(within(screen.getByTestId("reason-MECH-WEAR")).getByRole("button", { name: "Archive" }));
    await waitFor(() => expect(archive).toHaveBeenCalledWith(2));
  });

  it("is closed to operators", () => {
    renderWithProviders(<ReasonsPage />, { role: "machine_operator", ...ROUTE });

    expect(screen.getByText("Only factory managers can manage reasons.")).toBeInTheDocument();
  });
});
