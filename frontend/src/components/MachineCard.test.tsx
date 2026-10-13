import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { MachineState } from "../api/types.ts";
import { NOW_MS, iso, makeMachine } from "../test/fixtures.ts";
import { MachineCard } from "./MachineCard.tsx";

const SHIFT_START = iso(6 * 3600_000);

function renderCard(overrides: Parameters<typeof makeMachine>[0] = {}, isFirstStop = false) {
  return render(
    <MachineCard
      machine={makeMachine(overrides)}
      staleAfterSeconds={60}
      nowMs={NOW_MS}
      shiftStart={SHIFT_START}
      isFirstStop={isFirstStop}
    />,
  );
}

describe("MachineCard", () => {
  it.each<[MachineState, string]>([
    ["running", "Running"],
    ["stopped", "Stopped"],
    ["blocked", "Blocked"],
    ["starved", "Starved"],
    ["planned_stop", "Planned stop"],
    ["unknown", "Unknown"],
  ])("shows %s as written text with its own icon", (state, label) => {
    renderCard({ state });

    const card = screen.getByTestId("machine-M05");
    expect(card).toHaveTextContent(label);
    expect(card).toHaveAttribute("data-state", state);
    expect(card.querySelector(`[data-icon="${state}"]`)).not.toBeNull();
  });

  it("shows a stale machine as unknown, never its last state", () => {
    renderCard({ state: "running", last_seen: iso(5 * 60_000) });

    const card = screen.getByTestId("machine-M05");
    expect(card).toHaveTextContent("Unknown");
    expect(card).not.toHaveTextContent("Running");
    expect(card).toHaveTextContent("No recent data");
  });

  it("counts time in state up from state_since", () => {
    renderCard({ state: "stopped", state_since: iso(192_000) });

    expect(screen.getByTestId("machine-M05")).toHaveTextContent("for 3 min 12 s");
  });

  it("shows the current stop's alarm prominently when stopped", () => {
    renderCard({ state: "stopped", alarm_code: "E-204", last_alarm_code: "E-204", last_alarm_at: iso(60_000) });

    expect(screen.getByText("Alarm E-204")).toBeInTheDocument();
    expect(screen.queryByText(/Last alarm/)).toBeNull();
  });

  it("shows the last alarm small, with how long ago, on a running machine", () => {
    renderCard({ state: "running", last_alarm_code: "E-204", last_alarm_at: iso(42 * 60_000) });

    expect(screen.getByText("Last alarm E-204 · 42 min ago")).toBeInTheDocument();
    expect(screen.queryByText("Alarm E-204")).toBeNull();
  });

  it("hides an alarm older than the current shift", () => {
    renderCard({ state: "running", last_alarm_code: "E-204", last_alarm_at: iso(7 * 3600_000) });

    expect(screen.queryByText(/E-204/)).toBeNull();
  });

  it("shows the shift count", () => {
    renderCard({ shift_count: 15_100 });

    expect(screen.getByTestId("machine-M05")).toHaveTextContent("15,100");
  });

  it("labels the first observed stop", () => {
    renderCard({ state: "stopped" }, true);

    const card = screen.getByTestId("machine-M05");
    expect(card).toHaveAttribute("data-first-stop", "true");
    expect(card).toHaveTextContent("First observed stop");
  });
});
