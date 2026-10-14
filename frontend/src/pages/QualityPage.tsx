import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router";

import { getShiftOccurrences } from "../api/downtime.ts";
import {
  exportInspectionResultsCsv,
  getQualityPareto,
  getQualitySummary,
  getQualityTrend,
  listDefectTypes,
  listInspectionResults,
  listProducts,
  listStations,
} from "../api/quality.ts";
import type { InspectionResult } from "../api/qualityTypes.ts";
import { queryKeys } from "../api/queryKeys.ts";
import { IncidentDrawer } from "../components/downtime/IncidentDrawer.tsx";
import { LineNav } from "../components/LineNav.tsx";
import { Panel } from "../components/Panel.tsx";
import { DefectTrendChart } from "../components/quality/DefectTrendChart.tsx";
import { InspectionResultsTable } from "../components/quality/InspectionResultsTable.tsx";
import { QualityFilterBar } from "../components/quality/QualityFilterBar.tsx";
import { QualityParetoPanel } from "../components/quality/QualityParetoPanel.tsx";
import { QualitySummaryCards } from "../components/quality/QualitySummaryCards.tsx";
import { ReviewPanel } from "../components/quality/ReviewPanel.tsx";
import { t } from "../i18n/t.ts";
import { usePermissions } from "../lib/permissions.ts";
import { qualityFiltersToQuery, qualityGroupFilter, useQualityFilters } from "../lib/qualityFilters.ts";
import { type QuickRange, quickRange } from "../lib/quickRanges.ts";
import { serverNow } from "../lib/serverClock.ts";
import { fromLocalInput, toLocalInput } from "../lib/zonedTime.ts";
import { useLineContext } from "./useLineContext.ts";

const PAGE_SIZE = 50;
const DAY = 86_400_000;

export function QualityPage() {
  const lineId = Number(useParams().lineId);
  const { factory, shift } = useLineContext(lineId);
  const [filters, setFilters] = useQualityFilters();
  const { canReviewQuality } = usePermissions();
  const zone = factory.data?.timezone ?? "UTC";

  const [offset, setOffset] = useState(0);
  const [reviewing, setReviewing] = useState<InspectionResult | null>(null);
  const [drawer, setDrawer] = useState<number | null>(null);
  const [selectedGroup, setSelectedGroup] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState(false);

  // Without a range in the URL: the current shift (or today).
  const fallback = useMemo(
    () => quickRange("currentShift", { nowMs: serverNow(), zone, currentShift: shift.data ?? null, previousShifts: [] }),
    [shift.data, zone],
  );
  const effective = { ...filters, start: filters.start ?? fallback.start, end: filters.end ?? fallback.end };
  const base = qualityFiltersToQuery(lineId, effective);
  const ready = factory.isSuccess && shift.isFetched;

  useEffect(() => setOffset(0), [filters]);

  const stations = useQuery({ queryKey: queryKeys.stations(lineId), queryFn: () => listStations(lineId) });
  const defectTypes = useQuery({ queryKey: queryKeys.defectTypes(), queryFn: () => listDefectTypes() });
  const products = useQuery({ queryKey: ["products"], queryFn: listProducts });
  const summary = useQuery({
    queryKey: queryKeys.qualityAnalysis("summary", base),
    queryFn: () => getQualitySummary(base),
    enabled: ready,
  });
  const pareto = useQuery({
    queryKey: queryKeys.qualityAnalysis("pareto", { ...base, group_by: filters.group }),
    queryFn: () => getQualityPareto({ ...base, group_by: filters.group }),
    enabled: ready,
    placeholderData: keepPreviousData,
  });
  const trend = useQuery({
    queryKey: queryKeys.qualityAnalysis("trend", { ...base, group_by: filters.trend }),
    queryFn: () => getQualityTrend({ ...base, group_by: filters.trend }),
    enabled: ready,
    placeholderData: keepPreviousData,
  });
  const listQuery = { ...base, reviewed: filters.reviewed, limit: PAGE_SIZE, offset };
  const results = useQuery({
    queryKey: queryKeys.qualityAnalysis("results", listQuery),
    queryFn: () => listInspectionResults(listQuery),
    enabled: ready,
    placeholderData: keepPreviousData,
  });

  async function applyQuickRange(kind: QuickRange) {
    let previousShifts: Awaited<ReturnType<typeof getShiftOccurrences>> = [];
    if (kind === "lastShift" && factory.data) {
      const ref = shift.data ? Date.parse(shift.data.start) : serverNow();
      previousShifts = await getShiftOccurrences(
        factory.data.id,
        new Date(ref - 2 * DAY).toISOString(),
        new Date(ref).toISOString(),
      );
    }
    setFilters(quickRange(kind, { nowMs: serverNow(), zone, currentShift: shift.data ?? null, previousShifts }));
  }

  async function exportCsv() {
    setExporting(true);
    setExportError(false);
    try {
      const blob = await exportInspectionResultsCsv({ ...base, reviewed: filters.reviewed });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `quality-line-${lineId}.csv`;
      link.click();
      URL.revokeObjectURL(url);
    } catch {
      setExportError(true);
    } finally {
      setExporting(false);
    }
  }

  return (
    <main className="flex min-h-screen flex-col gap-4 bg-gray-100 p-4">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-3xl font-bold">{t("quality.title")}</h1>
        <p className="text-lg text-gray-600">{t("time.zone", { zone })}</p>
      </header>
      <LineNav lineId={lineId} shift={shift.data} />

      <QualityFilterBar
        filters={filters}
        onChange={(patch) => {
          setSelectedGroup(null);
          setFilters(patch);
        }}
        onQuickRange={(kind) => void applyQuickRange(kind)}
        stations={stations.data ?? []}
        defectTypes={defectTypes.data ?? []}
        products={products.data ?? []}
        startLocal={toLocalInput(effective.start, zone)}
        endLocal={toLocalInput(effective.end, zone)}
        onLocalRange={(start, end) => setFilters({ start: fromLocalInput(start, zone), end: fromLocalInput(end, zone) })}
      />

      <Panel isLoading={summary.isLoading} isError={summary.isError}>
        {summary.data && <QualitySummaryCards summary={summary.data} />}
      </Panel>

      <div className="grid gap-4 xl:grid-cols-2">
        <Panel isLoading={pareto.isLoading} isError={pareto.isError}>
          {pareto.data && (
            <QualityParetoPanel
              pareto={pareto.data}
              groupBy={filters.group}
              onGroupBy={(group) => setFilters({ group })}
              selectedKey={selectedGroup}
              onSelectGroup={(group) => {
                setSelectedGroup(group.key);
                setFilters(qualityGroupFilter(group));
              }}
            />
          )}
        </Panel>
        <Panel isLoading={trend.isLoading} isError={trend.isError}>
          {trend.data && (
            <DefectTrendChart trend={trend.data} groupBy={filters.trend} onGroupBy={(group) => setFilters({ trend: group })} />
          )}
        </Panel>
      </div>

      <Panel title={t("qtable.title")} isLoading={results.isLoading} isError={results.isError}>
        <div className="mb-3 flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => void exportCsv()}
            disabled={exporting}
            className="inline-flex min-h-12 items-center gap-2 rounded-lg border-2 border-gray-400 px-4 text-lg"
          >
            <Download aria-hidden className="h-5 w-5" />
            {exporting ? t("table.exporting") : t("table.export")}
          </button>
          {exportError && <p role="alert" className="text-lg text-red-700">{t("table.exportFailed")}</p>}
        </div>
        {results.data && (
          <InspectionResultsTable
            results={results.data.results}
            total={results.data.count}
            offset={offset}
            limit={PAGE_SIZE}
            zone={zone}
            canReview={canReviewQuality}
            onPage={setOffset}
            onReview={setReviewing}
            onOpenIncident={setDrawer}
          />
        )}
      </Panel>

      {saved && (
        <p role="status" className="fixed bottom-4 left-4 rounded-lg bg-green-800 px-4 py-3 text-xl text-white">
          {t("review.saved", { verdict: saved })}
        </p>
      )}
      {reviewing && (
        <ReviewPanel
          result={reviewing}
          zone={zone}
          canReview={canReviewQuality}
          onClose={() => setReviewing(null)}
          onSaved={setSaved}
        />
      )}
      {drawer !== null && <IncidentDrawer incidentId={drawer} zone={zone} onClose={() => setDrawer(null)} />}
    </main>
  );
}
