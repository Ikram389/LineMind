import { describe, expect, it } from "vitest";

import { makeQualityPareto } from "../test/qualityFixtures.ts";
import {
  parseQualityFilters,
  qualityFiltersToParams,
  qualityFiltersToQuery,
  qualityGroupFilter,
} from "./qualityFilters.ts";

describe("quality filters in the URL", () => {
  it("round-trips through the URL and ignores invalid values", () => {
    const params = new URLSearchParams(
      "start=2026-10-13T05:00:00Z&end=2026-10-13T13:00:00Z&group=machine&trend=day&station=4&defect_type=Q02&severity=critical&product=7&reviewed=false",
    );
    const filters = parseQualityFilters(params);

    expect(filters).toEqual({
      start: "2026-10-13T05:00:00Z", end: "2026-10-13T13:00:00Z", group: "machine", trend: "day",
      station: 4, machine: null, defectType: "Q02", severity: "critical", product: 7, reviewed: "false",
    });
    expect(qualityFiltersToParams(filters).toString()).toBe(params.toString());

    const odd = parseQualityFilters(new URLSearchParams("group=colour&severity=huge&reviewed=maybe&trend=week"));
    expect([odd.group, odd.severity, odd.reviewed, odd.trend]).toEqual(["defect_type", null, null, "hour"]);
    expect(qualityFiltersToParams(odd).toString()).toBe("");
  });

  it("builds the backend query", () => {
    const filters = parseQualityFilters(new URLSearchParams("defect_type=unknown&station=4"));

    expect(qualityFiltersToQuery(1, filters)).toEqual({
      line: 1, start: null, end: null, station: 4, machine: null, defect_type: "unknown", severity: null, product: null,
    });
  });

  it("turns a Pareto group into a filter", () => {
    const [known, unknown] = makeQualityPareto().groups;
    expect(known && qualityGroupFilter(known)).toEqual({ defectType: "Q02" });
    expect(unknown && qualityGroupFilter(unknown)).toEqual({ defectType: "unknown" });
    const station = { key: "station:4", id: 4, label: "Labeler", count: 3, share: 1, cumulative_share: 1 };
    expect(qualityGroupFilter(station)).toEqual({ station: 4 });
    expect(qualityGroupFilter({ ...station, key: "product:none", id: null })).toEqual({});
  });
});
