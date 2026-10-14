/** Quality endpoints (build step 9). */
import { apiDownload, apiFetch } from "./client.ts";
import { type DowntimeQuery, toQueryString } from "./downtime.ts";
import type {
  DefectType,
  InspectionResult,
  InspectionStation,
  QualityPareto,
  QualityReview,
  QualitySummary,
  QualityTrend,
  Severity,
  ShiftQuality,
  Verdict,
} from "./qualityTypes.ts";
import type { CurrentShift, Paginated } from "./types.ts";

export type QualityQuery = DowntimeQuery;

export const getQualitySummary = (params: QualityQuery): Promise<QualitySummary> =>
  apiFetch(`/quality/summary/?${toQueryString(params)}`);

export const getQualityPareto = (params: QualityQuery): Promise<QualityPareto> =>
  apiFetch(`/quality/pareto/?${toQueryString(params)}`);

export const getQualityTrend = (params: QualityQuery): Promise<QualityTrend> =>
  apiFetch(`/quality/trend/?${toQueryString(params)}`);

export const listInspectionResults = (params: QualityQuery): Promise<Paginated<InspectionResult>> =>
  apiFetch(`/inspection-results/?${toQueryString(params)}`);

export const exportInspectionResultsCsv = (params: QualityQuery): Promise<Blob> =>
  apiDownload(`/inspection-results/export.csv?${toQueryString(params)}`);

export const getReviews = (resultId: number): Promise<QualityReview[]> =>
  apiFetch(`/inspection-results/${resultId}/reviews/`);

export const reviewResult = (
  resultId: number,
  verdict: Verdict,
  correctedDefectType: number | null,
  comment: string,
): Promise<QualityReview> =>
  apiFetch(`/inspection-results/${resultId}/reviews/`, {
    method: "POST",
    body: JSON.stringify({ verdict, corrected_defect_type: correctedDefectType, comment }),
  });

/** The current shift's numbers for the overview card. */
export async function getShiftQuality(lineId: number, shift: CurrentShift | null): Promise<ShiftQuality> {
  if (!shift) return { shift: null, defects: 0, defect_rate: null, unreviewed: 0, total_count: 0 };
  const summary = await getQualitySummary({ line: lineId, start: shift.start, end: shift.end });
  return {
    shift: { label: shift.label, start: shift.start, end: shift.end },
    defects: summary.defects,
    defect_rate: summary.defect_rate,
    unreviewed: summary.unreviewed,
    total_count: summary.line_total_count,
  };
}

// --- Configuration ---------------------------------------------------------------------

export const listDefectTypes = (includeArchived = false): Promise<DefectType[]> =>
  apiFetch(`/defect-types/${includeArchived ? "?include_archived=true" : ""}`);

export interface DefectTypeInput {
  code: string;
  name: string;
  description: string;
  severity: Severity;
}

export const createDefectType = (input: DefectTypeInput): Promise<DefectType> =>
  apiFetch("/defect-types/", { method: "POST", body: JSON.stringify(input) });

export const updateDefectType = (id: number, input: DefectTypeInput): Promise<DefectType> =>
  apiFetch(`/defect-types/${id}/`, { method: "PATCH", body: JSON.stringify(input) });

export const setDefectTypeActive = (id: number, active: boolean): Promise<DefectType> =>
  apiFetch(`/defect-types/${id}/${active ? "restore" : "archive"}/`, { method: "POST" });

export const deleteDefectType = (id: number): Promise<null> =>
  apiFetch(`/defect-types/${id}/`, { method: "DELETE" });

export const listStations = (lineId: number, includeArchived = false): Promise<InspectionStation[]> =>
  apiFetch(`/inspection-stations/?line=${lineId}${includeArchived ? "&include_archived=true" : ""}`);

export interface StationInput {
  line: number;
  machine: number;
  name: string;
  defect_types: number[];
  source: "simulator" | "vision";
}

export const createStation = (input: StationInput): Promise<InspectionStation> =>
  apiFetch("/inspection-stations/", { method: "POST", body: JSON.stringify(input) });

export const updateStation = (id: number, input: Partial<StationInput>): Promise<InspectionStation> =>
  apiFetch(`/inspection-stations/${id}/`, { method: "PATCH", body: JSON.stringify(input) });

export const setStationActive = (id: number, active: boolean): Promise<InspectionStation> =>
  apiFetch(`/inspection-stations/${id}/${active ? "restore" : "archive"}/`, { method: "POST" });

export const deleteStation = (id: number): Promise<null> =>
  apiFetch(`/inspection-stations/${id}/`, { method: "DELETE" });

export interface ProductSummary {
  id: number;
  sku: string;
  name: string;
}

/** Products of the organization (for the product filter). */
export const listProducts = (): Promise<ProductSummary[]> => apiFetch("/products/");
