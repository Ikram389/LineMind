/**
 * Downtime page filters, kept in the URL so a view can be bookmarked and shared.
 * Example: /lines/1/downtime?start=…&end=…&view=machine&group=machine&category=breakdown
 */
import { useCallback, useMemo } from "react";
import { useSearchParams } from "react-router";

import type { AnalysisView, ParetoGroupBy } from "../api/analysisTypes.ts";
import type { DowntimeQuery } from "../api/downtime.ts";

export interface DowntimeFilters {
  start: string | null;
  end: string | null;
  view: AnalysisView;
  group: ParetoGroupBy;
  machine: number | null;
  category: string | null; // comma-separated categories
  reason: string | null; // reason code or "unclassified"
  alarm: string | null; // set by clicking an alarm-code bar
  classified: "true" | "false" | null;
  minDuration: number | null;
  includePlanned: boolean;
  includeNoData: boolean;
}

const GROUPS: ParetoGroupBy[] = ["reason", "machine", "category", "alarm_code"];

const int = (value: string | null): number | null => {
  if (value === null || value === "") return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
};

export function parseFilters(params: URLSearchParams): DowntimeFilters {
  const group = params.get("group");
  const classified = params.get("classified");
  return {
    start: params.get("start"),
    end: params.get("end"),
    view: params.get("view") === "machine" ? "machine" : "line",
    group: GROUPS.includes(group as ParetoGroupBy) ? (group as ParetoGroupBy) : "reason",
    machine: int(params.get("machine")),
    category: params.get("category"),
    reason: params.get("reason"),
    alarm: params.get("alarm"),
    classified: classified === "true" || classified === "false" ? classified : null,
    minDuration: int(params.get("min_duration")),
    includePlanned: params.get("planned") === "1",
    includeNoData: params.get("no_data") === "1",
  };
}

export function filtersToParams(filters: DowntimeFilters): URLSearchParams {
  const params = new URLSearchParams();
  const set = (key: string, value: string | number | null | boolean) => {
    if (value === null || value === false || value === "") return;
    params.set(key, value === true ? "1" : String(value));
  };
  set("start", filters.start);
  set("end", filters.end);
  if (filters.view !== "line") set("view", filters.view);
  if (filters.group !== "reason") set("group", filters.group);
  set("machine", filters.machine);
  set("category", filters.category);
  set("reason", filters.reason);
  set("alarm", filters.alarm);
  set("classified", filters.classified);
  set("min_duration", filters.minDuration);
  set("planned", filters.includePlanned);
  set("no_data", filters.includeNoData);
  return params;
}

/** The backend query for these filters (line view by default). */
export function filtersToQuery(lineId: number, filters: DowntimeFilters): DowntimeQuery {
  const include = [filters.includePlanned && "planned", filters.includeNoData && "no_data"]
    .filter(Boolean)
    .join(",");
  return {
    line: lineId,
    start: filters.start,
    end: filters.end,
    view: filters.view,
    machine: filters.machine,
    category: filters.category,
    reason: filters.reason,
    alarm: filters.alarm,
    classified: filters.classified,
    min_duration: filters.minDuration,
    include: include || undefined,
  };
}

/** Read and update the filters in the URL. */
export function useDowntimeFilters(): [DowntimeFilters, (patch: Partial<DowntimeFilters>) => void] {
  const [params, setParams] = useSearchParams();
  const filters = useMemo(() => parseFilters(params), [params]);
  const update = useCallback(
    (patch: Partial<DowntimeFilters>) => {
      setParams(filtersToParams({ ...parseFilters(params), ...patch }), { replace: true });
    },
    [params, setParams],
  );
  return [filters, update];
}
