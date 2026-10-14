/**
 * Quality page filters, kept in the URL like the downtime page.
 * Example: /lines/1/quality?start=…&end=…&group=station&defect_type=Q02&reviewed=false
 */
import { useCallback, useMemo } from "react";
import { useSearchParams } from "react-router";

import type { QualityQuery } from "../api/quality.ts";
import {
  type QualityGroupBy,
  type QualityParetoGroup,
  SEVERITIES,
  type Severity,
  type TrendGroupBy,
} from "../api/qualityTypes.ts";

export interface QualityFilters {
  start: string | null;
  end: string | null;
  group: QualityGroupBy;
  trend: TrendGroupBy;
  station: number | null;
  machine: number | null;
  defectType: string | null; // effective code, or "unknown"
  severity: Severity | null;
  product: number | null;
  reviewed: "true" | "false" | null;
}

const GROUPS: QualityGroupBy[] = ["defect_type", "station", "machine", "product"];
const TRENDS: TrendGroupBy[] = ["hour", "shift", "day"];

const int = (value: string | null): number | null => {
  if (value === null || value === "") return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
};

export function parseQualityFilters(params: URLSearchParams): QualityFilters {
  const group = params.get("group");
  const trend = params.get("trend");
  const severity = params.get("severity");
  const reviewed = params.get("reviewed");
  return {
    start: params.get("start"),
    end: params.get("end"),
    group: GROUPS.includes(group as QualityGroupBy) ? (group as QualityGroupBy) : "defect_type",
    trend: TRENDS.includes(trend as TrendGroupBy) ? (trend as TrendGroupBy) : "hour",
    station: int(params.get("station")),
    machine: int(params.get("machine")),
    defectType: params.get("defect_type"),
    severity: SEVERITIES.includes(severity as Severity) ? (severity as Severity) : null,
    product: int(params.get("product")),
    reviewed: reviewed === "true" || reviewed === "false" ? reviewed : null,
  };
}

export function qualityFiltersToParams(filters: QualityFilters): URLSearchParams {
  const params = new URLSearchParams();
  const set = (key: string, value: string | number | null) => {
    if (value !== null && value !== "") params.set(key, String(value));
  };
  set("start", filters.start);
  set("end", filters.end);
  if (filters.group !== "defect_type") set("group", filters.group);
  if (filters.trend !== "hour") set("trend", filters.trend);
  set("station", filters.station);
  set("machine", filters.machine);
  set("defect_type", filters.defectType);
  set("severity", filters.severity);
  set("product", filters.product);
  set("reviewed", filters.reviewed);
  return params;
}

/** The backend query for these filters (shared by summary, Pareto, trend, list and CSV). */
export function qualityFiltersToQuery(lineId: number, filters: QualityFilters): QualityQuery {
  return {
    line: lineId,
    start: filters.start,
    end: filters.end,
    station: filters.station,
    machine: filters.machine,
    defect_type: filters.defectType,
    severity: filters.severity,
    product: filters.product,
  };
}

/** Turn a clicked Pareto group into the matching filter. */
export function qualityGroupFilter(group: QualityParetoGroup): Partial<QualityFilters> {
  const kind = group.key.split(":")[0];
  if (kind === "defect_type") return { defectType: group.id === null ? "unknown" : (group.code ?? null) };
  if (group.id === null) return {};
  if (kind === "station") return { station: group.id };
  if (kind === "machine") return { machine: group.id };
  if (kind === "product") return { product: group.id };
  return {};
}

export function useQualityFilters(): [QualityFilters, (patch: Partial<QualityFilters>) => void] {
  const [params, setParams] = useSearchParams();
  const filters = useMemo(() => parseQualityFilters(params), [params]);
  const update = useCallback(
    (patch: Partial<QualityFilters>) => {
      setParams(qualityFiltersToParams({ ...parseQualityFilters(params), ...patch }), { replace: true });
    },
    [params, setParams],
  );
  return [filters, update];
}
