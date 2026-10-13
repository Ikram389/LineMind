import { describe, expect, it } from "vitest";

import { formatClock, formatDuration, formatShortDuration, formatTime } from "./time.ts";

describe("formatDuration", () => {
  it.each([
    [0, "0 s"],
    [59, "59 s"],
    [192, "3 min 12 s"],
    [3720, "1 h 02 min"],
    [93_900, "1 d 2 h"],
    [-5, "0 s"],
  ])("%i s -> %s", (seconds, text) => {
    expect(formatDuration(seconds)).toBe(text);
  });

  it("short form drops seconds after a minute", () => {
    expect(formatShortDuration(42 * 60 + 30)).toBe("42 min");
    expect(formatShortDuration(30)).toBe("30 s");
  });
});

describe("times in the factory timezone", () => {
  const instant = "2026-10-13T12:05:09Z";

  it("shows Algiers local time (UTC+1), not the device's", () => {
    expect(formatClock(instant, "Africa/Algiers")).toBe("13:05:09");
    expect(formatTime(instant, "Africa/Algiers")).toBe("13:05");
  });

  it("follows the zone it is given", () => {
    expect(formatTime(instant, "UTC")).toBe("12:05");
    expect(formatTime(instant, "Asia/Tokyo")).toBe("21:05");
  });
});
