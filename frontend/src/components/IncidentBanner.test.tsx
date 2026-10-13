import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import { NOW_MS, makeIncident, makeMachine } from "../test/fixtures.ts";
import { IncidentBanner } from "./IncidentBanner.tsx";
import { MachineFlow } from "./MachineFlow.tsx";

describe("IncidentBanner", () => {
  it("names the first observed stop with its alarm and the duration", () => {
    render(<IncidentBanner incident={makeIncident()} nowMs={NOW_MS} />);

    expect(screen.getByTestId("incident-headline")).toHaveTextContent(
      "Line stopped for 3 min 12 s — first observed stop: Labeler (alarm E-204)",
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Affected machines: Capper (blocked) · Packer (starved)",
    );
  });

  it("never claims a cause", () => {
    render(<IncidentBanner incident={makeIncident()} nowMs={NOW_MS} />);

    expect(screen.getByRole("alert").textContent?.toLowerCase()).not.toContain("root cause");
  });

  it("names every simultaneous first stop", () => {
    const incident = makeIncident({
      first_observed_stop: {
        machines: [
          { id: 3, external_id: "M03", name: "Filler" },
          { id: 5, external_id: "M05", name: "Labeler" },
        ],
        alarm_code: null,
      },
    });
    render(<IncidentBanner incident={incident} nowMs={NOW_MS} />);

    expect(screen.getByTestId("incident-headline")).toHaveTextContent(
      "first observed stop: Filler + Labeler",
    );
  });

  it("says when the origin is unknown", () => {
    const incident = makeIncident({ origin: "unknown", first_observed_stop: { machines: [], alarm_code: null } });
    render(<IncidentBanner incident={incident} nowMs={NOW_MS} />);

    expect(screen.getByTestId("incident-headline")).toHaveTextContent("origin unknown");
  });
});

describe("MachineFlow", () => {
  it("highlights only the first observed stop's card", () => {
    const machines = [
      makeMachine({ id: 4, external_id: "M04", name: "Capper", position: 4, state: "blocked" }),
      makeMachine({ id: 5, external_id: "M05", name: "Labeler", position: 5, state: "stopped" }),
      makeMachine({ id: 6, external_id: "M06", name: "Packer", position: 6, state: "starved" }),
    ];
    render(
      <MemoryRouter>
        <MachineFlow
          machines={machines}
          incident={makeIncident()}
          staleAfterSeconds={60}
          nowMs={NOW_MS}
          shiftStart={null}
          machineHref={(m) => `/lines/1/machines/${m.id}`}
        />
      </MemoryRouter>,
    );

    expect(screen.getByTestId("machine-M05")).toHaveAttribute("data-first-stop", "true");
    expect(screen.getByTestId("machine-M04")).not.toHaveAttribute("data-first-stop");
    expect(screen.getByTestId("machine-M06")).not.toHaveAttribute("data-first-stop");
    expect(screen.getAllByText("First observed stop")).toHaveLength(1);
  });

  it("shows machines in line order", () => {
    const machines = [
      makeMachine({ id: 6, external_id: "M06", position: 6 }),
      makeMachine({ id: 1, external_id: "M01", position: 1 }),
    ];
    render(
      <MemoryRouter>
        <MachineFlow
          machines={machines}
          incident={null}
          staleAfterSeconds={60}
          nowMs={NOW_MS}
          shiftStart={null}
          machineHref={() => "/"}
        />
      </MemoryRouter>,
    );

    const ids = screen.getAllByTestId(/^machine-/).map((el) => el.getAttribute("data-testid"));
    expect(ids).toEqual(["machine-M01", "machine-M06"]);
  });
});
