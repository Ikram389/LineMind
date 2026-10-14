import { screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import * as downtime from "../../api/downtime.ts";
import { makeMember } from "../../test/downtimeFixtures.ts";
import { renderWithProviders } from "../../test/render.tsx";
import { IncidentDrawer } from "./IncidentDrawer.tsx";
import { SummaryCards } from "./SummaryCards.tsx";

describe("IncidentDrawer", () => {
  it("marks a second, independent breakdown as a secondary breakdown", async () => {
    vi.spyOn(downtime, "getIncident").mockResolvedValue({
      id: 7, line: { id: 1, name: "Bottling Line 1" }, started_at: "2026-10-13T09:05:00Z",
      ended_at: "2026-10-13T09:06:31Z", duration_seconds: 91, is_ongoing: false, origin: "machine_stop",
      events: [
        makeMember({ id: 11, role_in_incident: "first_observed_stop" }),
        makeMember({
          id: 12, machine: { id: 4, external_id: "M04", name: "Capper", position: 4 },
          category: "blocked", is_first_stop: false, role_in_incident: "consequence", alarm_code: null, delay_seconds: 3,
        }),
        makeMember({
          id: 13, machine: { id: 3, external_id: "M03", name: "Filler", position: 3 },
          is_first_stop: false, role_in_incident: "secondary_breakdown", alarm_code: "E-301", delay_seconds: 20,
        }),
      ],
    });
    renderWithProviders(<IncidentDrawer incidentId={7} zone="UTC" onClose={() => {}} />);

    const items = await screen.findAllByRole("listitem");
    const [labeler, capper, filler] = items.map((item) => within(item));
    expect(labeler?.getByText("First observed stop")).toBeInTheDocument();
    expect(capper?.getByText("Consequence")).toBeInTheDocument();
    expect(filler?.getByText("Secondary breakdown")).toBeInTheDocument();
    expect(filler?.getByText(/E-301/)).toBeInTheDocument();
    // Breakdowns need a reason, so their history is shown; consequences never need one.
    expect(filler?.getByText("Not classified yet")).toBeInTheDocument();
    expect(capper?.queryByText("Not classified yet")).toBeNull();
  });
});

describe("SummaryCards", () => {
  it("says how many line stops had more than one breakdown", () => {
    renderWithProviders(
      <SummaryCards
        summary={{
          view: "line", view_note: "", total_seconds: 300, stops: 3, unclassified: 2, secondary_breakdowns: 1,
          longest: null, estimated_lost_units: { units: 500, is_estimate: true, basis: "" },
        }}
      />,
    );

    expect(screen.getByText("1 line stops had more than one breakdown")).toBeInTheDocument();
  });
});
