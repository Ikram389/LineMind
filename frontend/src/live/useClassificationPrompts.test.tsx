import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as downtime from "../api/downtime.ts";
import { LineNav } from "../components/LineNav.tsx";
import { QuickClassifyCard } from "../components/QuickClassifyCard.tsx";
import { REASONS, makeMember } from "../test/downtimeFixtures.ts";
import { renderWithProviders } from "../test/render.tsx";
import { promptsForIncident, useClassificationPrompts } from "./useClassificationPrompts.ts";

const SHIFT = {
  shift_id: 1, name: "Morning", label: "Morning 2026-10-13", local_date: "2026-10-13",
  start: "2026-10-13T05:00:00Z", end: "2026-10-13T13:00:00Z", breaks: [], factory_timezone: "Africa/Algiers",
};

const labeler = makeMember({ id: 11, role_in_incident: "first_observed_stop" });
const capper = makeMember({
  id: 12, machine: { id: 4, external_id: "M04", name: "Capper", position: 4 },
  category: "blocked", is_first_stop: false, role_in_incident: "consequence", alarm_code: null,
});
const filler = makeMember({
  id: 13, machine: { id: 3, external_id: "M03", name: "Filler", position: 3 },
  is_first_stop: false, role_in_incident: "secondary_breakdown", alarm_code: "E-301",
  started_at: "2026-10-13T09:05:20Z",
});

let fire: ((message: Parameters<ReturnType<typeof useClassificationPrompts>["onMessage"]>[0]) => void) | null = null;

function Harness() {
  const { prompts, onMessage, dismiss } = useClassificationPrompts();
  fire = onMessage;
  const first = prompts[0];
  return (
    <>
      <LineNav lineId={1} shift={SHIFT} />
      {first && (
        <QuickClassifyCard key={first.id} event={first} onMore={() => {}} onLater={() => dismiss(first.id)} onDone={() => dismiss(first.id)} />
      )}
    </>
  );
}

const closed = {
  type: "incident_closed" as const,
  line_id: 1,
  sent_at: "2026-10-13T09:06:31Z",
  data: { incident_id: 7, started_at: "2026-10-13T09:05:00Z", ended_at: "2026-10-13T09:06:31Z", duration_seconds: 91 },
};

beforeEach(() => {
  vi.spyOn(downtime, "getIncident").mockResolvedValue({
    id: 7, line: { id: 1, name: "Bottling Line 1" }, started_at: "2026-10-13T09:05:00Z",
    ended_at: "2026-10-13T09:06:31Z", duration_seconds: 91, is_ongoing: false, origin: "machine_stop",
    events: [capper, filler, labeler],
  });
  vi.spyOn(downtime, "getSuggestedReasons").mockResolvedValue([...REASONS.slice(2, 3), ...REASONS.slice(0, 1)]);
});

describe("prompts after a line stop", () => {
  it("asks for the first observed stop, then secondary breakdowns, never consequences", () => {
    expect(promptsForIncident([capper, filler, labeler]).map((m) => m.id)).toEqual([11, 13]);
    expect(promptsForIncident([{ ...labeler, classification: { id: 1, reason: { id: 1, code: "X", name: "X", category: "mechanical" }, comment: "", source: "operator", created_by: null, created_at: "" } }])).toEqual([]);
  });

  it("shows the prompt when the stop ends; Later keeps the stop in the queue", async () => {
    const counts = vi.spyOn(downtime, "countUnclassified").mockResolvedValue(2);
    const classify = vi.spyOn(downtime, "classifyEvent");
    renderWithProviders(<Harness />);
    expect(await screen.findByTestId("unclassified-badge")).toHaveTextContent("Unclassified 2");

    act(() => fire?.(closed));

    expect(await screen.findByText(/Why did the Labeler stop\?/)).toHaveTextContent("(3 min 12 s, alarm E-204)");
    expect(screen.queryByText(/Capper/)).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Later" }));

    // Next: the secondary breakdown. The Labeler was not classified, so it stays counted.
    expect(await screen.findByText(/Why did the Filler stop\?/)).toBeInTheDocument();
    expect(screen.getByText("A second breakdown in the same line stop")).toBeInTheDocument();
    expect(classify).not.toHaveBeenCalled();
    expect(screen.getByTestId("unclassified-badge")).toHaveTextContent("Unclassified 2");
    expect(counts).toHaveBeenCalled();
  });

  it("choosing a reason saves it and the badge count goes down", async () => {
    const counts = vi.spyOn(downtime, "countUnclassified").mockResolvedValueOnce(2).mockResolvedValue(1);
    const classify = vi.spyOn(downtime, "classifyEvent").mockResolvedValue({
      id: 9, reason: { id: 3, code: "MAT-LABEL", name: "Label roll empty", category: "material" },
      comment: "", source: "operator", created_by: null, created_at: "2026-10-13T09:07:00Z",
    });
    renderWithProviders(<Harness />);
    expect(await screen.findByTestId("unclassified-badge")).toHaveTextContent("Unclassified 2");

    act(() => fire?.(closed));
    fireEvent.click(await screen.findByRole("button", { name: "Label roll empty" }));

    await waitFor(() => expect(classify).toHaveBeenCalledWith(11, 3, ""));
    await waitFor(() => expect(screen.getByTestId("unclassified-badge")).toHaveTextContent("Unclassified 1"));
    expect(counts.mock.calls.length).toBeGreaterThanOrEqual(2);
  });
});

describe("LineNav permissions", () => {
  it("shows Reasons only to managers", async () => {
    vi.spyOn(downtime, "countUnclassified").mockResolvedValue(0);
    const operator = renderWithProviders(<LineNav lineId={1} shift={SHIFT} />, { role: "machine_operator" });
    expect(screen.queryByRole("link", { name: "Reasons" })).toBeNull();
    operator.unmount();

    renderWithProviders(<LineNav lineId={1} shift={SHIFT} />, { role: "factory_manager" });
    expect(screen.getByRole("link", { name: "Reasons" })).toBeInTheDocument();
  });
});
