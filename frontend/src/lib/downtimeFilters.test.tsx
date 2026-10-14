import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter, useLocation } from "react-router";
import { describe, expect, it } from "vitest";

import { filtersToParams, filtersToQuery, parseFilters, useDowntimeFilters } from "./downtimeFilters.ts";
import { quickRange } from "./quickRanges.ts";

describe("downtime filters in the URL", () => {
  it("reads every filter from the URL", () => {
    const filters = parseFilters(
      new URLSearchParams(
        "start=2026-10-13T05:00:00Z&end=2026-10-13T13:00:00Z&view=machine&group=alarm_code&machine=5&category=breakdown&reason=unclassified&classified=false&min_duration=60&planned=1",
      ),
    );

    expect(filters).toMatchObject({
      start: "2026-10-13T05:00:00Z",
      end: "2026-10-13T13:00:00Z",
      view: "machine",
      group: "alarm_code",
      machine: 5,
      category: "breakdown",
      reason: "unclassified",
      classified: "false",
      minDuration: 60,
      includePlanned: true,
      includeNoData: false,
    });
  });

  it("writes them back so a view can be bookmarked", () => {
    const params = new URLSearchParams("view=machine&reason=MECH-JAM&no_data=1&start=x&end=y");
    expect(filtersToParams(parseFilters(params)).toString()).toBe(
      "start=x&end=y&view=machine&reason=MECH-JAM&no_data=1",
    );
  });

  it("turns filters into the backend query", () => {
    const query = filtersToQuery(1, parseFilters(new URLSearchParams("planned=1&no_data=1&reason=MECH-JAM")));
    expect(query).toMatchObject({ line: 1, view: "line", reason: "MECH-JAM", include: "planned,no_data" });
  });

  it("updates the URL when a filter changes", () => {
    let location = "";
    function Spy({ children }: { children: ReactNode }) {
      const loc = useLocation();
      location = loc.search;
      return <>{children}</>;
    }
    const { result } = renderHook(() => useDowntimeFilters(), {
      wrapper: ({ children }) => (
        <MemoryRouter initialEntries={["/lines/1/downtime?view=machine"]}>
          <Spy>{children}</Spy>
        </MemoryRouter>
      ),
    });

    expect(result.current[0].view).toBe("machine");
    act(() => result.current[1]({ category: "starved", view: "line" }));

    expect(result.current[0].category).toBe("starved");
    expect(location).toBe("?category=starved");
  });
});

describe("quick ranges use the factory's calendar", () => {
  const ctx = {
    nowMs: Date.parse("2026-10-13T11:30:00Z"), // 12:30 in Algiers
    zone: "Africa/Algiers",
    currentShift: null,
    previousShifts: [],
  };

  it("today and yesterday start at local midnight", () => {
    expect(quickRange("today", ctx)).toEqual({
      start: "2026-10-12T23:00:00.000Z",
      end: "2026-10-13T23:00:00.000Z",
    });
    expect(quickRange("yesterday", ctx).start).toBe("2026-10-11T23:00:00.000Z");
  });

  it("last shift is the latest shift that ended before the current one", () => {
    const range = quickRange("lastShift", {
      ...ctx,
      currentShift: {
        shift_id: 1, name: "Morning", label: "Morning 2026-10-13", local_date: "2026-10-13",
        start: "2026-10-13T05:00:00Z", end: "2026-10-13T13:00:00Z", breaks: [], factory_timezone: "Africa/Algiers",
      },
      previousShifts: [
        { shift_id: 2, name: "Afternoon", label: "", local_date: "2026-10-12", start: "2026-10-12T13:00:00Z", end: "2026-10-12T21:00:00Z" },
        { shift_id: 3, name: "Night", label: "", local_date: "2026-10-12", start: "2026-10-12T21:00:00Z", end: "2026-10-13T05:00:00Z" },
      ],
    });
    expect(range).toEqual({ start: "2026-10-12T21:00:00Z", end: "2026-10-13T05:00:00Z" });
  });
});
