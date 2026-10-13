import { describe, expect, it, vi } from "vitest";

import { makeMachine } from "../test/fixtures.ts";
import { recordDateHeader, recordServerTime, serverNow } from "./serverClock.ts";
import { effectiveState } from "./states.ts";
import { formatDuration, secondsBetween } from "./time.ts";

const SERVER = Date.parse("2026-10-13T12:00:00.000Z");
const THREE_MIN = 3 * 60 * 1000;

describe("server time with a device clock 3 minutes off", () => {
  it("corrects the device clock from a WebSocket sent_at", () => {
    vi.useFakeTimers();
    vi.setSystemTime(SERVER + THREE_MIN); // tablet clock is 3 minutes fast

    recordServerTime(SERVER);

    expect(serverNow()).toBe(SERVER);
  });

  it("corrects the device clock from an HTTP Date header", () => {
    vi.useFakeTimers();
    vi.setSystemTime(SERVER - THREE_MIN); // tablet clock is 3 minutes slow

    recordDateHeader(new Date(SERVER).toUTCString());

    expect(Math.abs(serverNow() - SERVER)).toBeLessThanOrEqual(1000);
  });

  it("uses server time for stale detection and time in state", () => {
    // Last data 30 s ago (server time): fresh. The device, 3 min fast, would call it stale.
    const machine = makeMachine({
      state: "stopped",
      state_since: new Date(SERVER - 72_000).toISOString(),
      last_seen: new Date(SERVER - 30_000).toISOString(),
    });
    vi.useFakeTimers();
    vi.setSystemTime(SERVER + THREE_MIN);

    expect(effectiveState(machine, 60, Date.now()).state).toBe("unknown"); // device clock: wrong

    recordServerTime(SERVER);
    const shown = effectiveState(machine, 60, serverNow());
    expect(shown.state).toBe("stopped");
    expect(formatDuration(secondsBetween(shown.since ?? "", serverNow()))).toBe("1 min 12 s");
  });

  it("ignores a Date header that only disagrees by rounding", () => {
    vi.useFakeTimers();
    vi.setSystemTime(SERVER);
    recordServerTime(SERVER + 400); // precise sample: server is 0.4 s ahead

    recordDateHeader(new Date(SERVER).toUTCString());

    expect(serverNow() - Date.now()).toBe(400);
  });
});
