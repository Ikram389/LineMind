import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router";

import type { AnalysedDowntimeEvent } from "../api/analysisTypes.ts";
import {
  exportDowntimeCsv,
  getDowntimeSummary,
  getPareto,
  getRecurring,
  getShiftOccurrences,
  listDowntimeEvents,
  listLineMachines,
  listReasons,
} from "../api/downtime.ts";
import { queryKeys } from "../api/queryKeys.ts";
import { ClassifyPanel } from "../components/ClassifyPanel.tsx";
import { DowntimeEventsTable } from "../components/downtime/DowntimeEventsTable.tsx";
import { FilterBar } from "../components/downtime/FilterBar.tsx";
import { IncidentDrawer } from "../components/downtime/IncidentDrawer.tsx";
import { ParetoPanel } from "../components/downtime/ParetoPanel.tsx";
import { RecurringPanel } from "../components/downtime/RecurringPanel.tsx";
import { SummaryCards } from "../components/downtime/SummaryCards.tsx";
import { LineNav } from "../components/LineNav.tsx";
import { Panel } from "../components/Panel.tsx";
import { t } from "../i18n/t.ts";
import type { ClassifyTarget } from "../lib/classifyTarget.ts";
import { type DowntimeFilters, filtersToQuery, useDowntimeFilters } from "../lib/downtimeFilters.ts";
import { usePermissions } from "../lib/permissions.ts";
import { type QuickRange, quickRange } from "../lib/quickRanges.ts";
import { serverNow } from "../lib/serverClock.ts";
import { fromLocalInput, toLocalInput } from "../lib/zonedTime.ts";
import { useLineContext } from "./useLineContext.ts";

const PAGE_SIZE = 50;
const DAY = 86_400_000;

/** Turn a Pareto group key into the matching filter. */
function groupFilter(key: string, reasonCodes: Map<number, string>): Partial<DowntimeFilters> {
  const [kind, value] = key.split(":");
  if (key === "unclassified") return { reason: "unclassified" };
  if (kind === "reason" && value) return { reason: reasonCodes.get(Number(value)) ?? null };
  if (kind === "machine" && value) return { machine: Number(value) };
  if (kind === "category" && value) return { category: value };
  if (kind === "alarm") return { alarm: value || "none" };
  return {};
}

export function DowntimePage() {
  const lineId = Number(useParams().lineId);
  const { factory, shift } = useLineContext(lineId);
  const [filters, setFilters] = useDowntimeFilters();
  const permissions = usePermissions();
  const zone = factory.data?.timezone ?? "UTC";

  const [offset, setOffset] = useState(0);
  const [ordering, setOrdering] = useState("-started_at");
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [classifying, setClassifying] = useState<ClassifyTarget[] | null>(null);
  const [drawer, setDrawer] = useState<number | null>(null);
  const [selectedGroup, setSelectedGroup] = useState<string | null>(null);
  const [exportError, setExportError] = useState(false);
  const [exporting, setExporting] = useState(false);

  // Without a range in the URL: the current shift (or today).
  const fallback = useMemo(
    () =>
      quickRange("currentShift", {
        nowMs: serverNow(),
        zone,
        currentShift: shift.data ?? null,
        previousShifts: [],
      }),
    [shift.data, zone],
  );
  const effective = { ...filters, start: filters.start ?? fallback.start, end: filters.end ?? fallback.end };
  const base = filtersToQuery(lineId, effective);
  const ready = factory.isSuccess && shift.isFetched;

  useEffect(() => {
    setOffset(0);
    setSelected(new Set());
  }, [filters]);

  const machines = useQuery({ queryKey: ["lineMachines", lineId], queryFn: () => listLineMachines(lineId) });
  const reasons = useQuery({
    queryKey: queryKeys.reasons(factory.data?.id ?? 0, true),
    queryFn: () => listReasons(factory.data?.id ?? 0, true),
    enabled: factory.isSuccess,
  });
  const summary = useQuery({
    queryKey: queryKeys.downtimeAnalysis("summary", base),
    queryFn: () => getDowntimeSummary(base),
    enabled: ready,
  });
  const pareto = useQuery({
    queryKey: queryKeys.downtimeAnalysis("pareto", { ...base, group_by: filters.group }),
    queryFn: () => getPareto({ ...base, group_by: filters.group }),
    enabled: ready,
    placeholderData: keepPreviousData,
  });
  const recurring = useQuery({
    queryKey: queryKeys.downtimeAnalysis("recurring", base),
    queryFn: () => getRecurring(base),
    enabled: ready,
  });
  const listQuery = { ...base, limit: PAGE_SIZE, offset, ordering };
  const events = useQuery({
    queryKey: queryKeys.downtimeAnalysis("events", listQuery),
    queryFn: () => listDowntimeEvents(listQuery),
    enabled: ready,
    placeholderData: keepPreviousData,
  });

  const reasonCodes = useMemo(
    () => new Map((reasons.data ?? []).map((r) => [r.id, r.code] as const)),
    [reasons.data],
  );

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
    const range = quickRange(kind, { nowMs: serverNow(), zone, currentShift: shift.data ?? null, previousShifts });
    setFilters(range);
  }

  async function exportCsv() {
    setExporting(true);
    setExportError(false);
    try {
      const blob = await exportDowntimeCsv(base);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `downtime-line-${lineId}.csv`;
      link.click();
      URL.revokeObjectURL(url);
    } catch {
      setExportError(true);
    } finally {
      setExporting(false);
    }
  }

  const selectedEvents = (events.data?.results ?? []).filter((e) => selected.has(e.id));

  return (
    <main className="flex min-h-screen flex-col gap-4 bg-gray-100 p-4">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-3xl font-bold">{t("downtime.title")}</h1>
        <p className="text-lg text-gray-600">{t("time.zone", { zone })}</p>
      </header>
      <LineNav lineId={lineId} shift={shift.data} />

      <FilterBar
        filters={filters}
        onChange={(patch) => {
          setSelectedGroup(null);
          setFilters(patch);
        }}
        onQuickRange={(kind) => void applyQuickRange(kind)}
        machines={machines.data ?? []}
        reasons={reasons.data ?? []}
        startLocal={toLocalInput(effective.start, zone)}
        endLocal={toLocalInput(effective.end, zone)}
        onLocalRange={(start, end) =>
          setFilters({ start: fromLocalInput(start, zone), end: fromLocalInput(end, zone) })
        }
      />

      <Panel isLoading={summary.isLoading} isError={summary.isError}>
        {summary.data && <SummaryCards summary={summary.data} />}
      </Panel>

      <div className="grid gap-4 xl:grid-cols-[2fr_1fr]">
        <Panel isLoading={pareto.isLoading} isError={pareto.isError}>
          {pareto.data && (
            <ParetoPanel
              pareto={pareto.data}
              groupBy={filters.group}
              onGroupBy={(group) => setFilters({ group })}
              selectedKey={selectedGroup}
              onSelectGroup={(key) => {
                setSelectedGroup(key);
                setFilters(groupFilter(key, reasonCodes));
              }}
            />
          )}
        </Panel>
        <Panel isLoading={recurring.isLoading} isError={recurring.isError}>
          {recurring.data && (
            <RecurringPanel
              recurring={recurring.data}
              zone={zone}
              range={effective.start && effective.end ? { start: effective.start, end: effective.end } : undefined}
            />
          )}
        </Panel>
      </div>

      <Panel title={t("table.title")} isLoading={events.isLoading} isError={events.isError}>
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
          {permissions.canBulkClassify && selected.size > 0 && (
            <button
              type="button"
              onClick={() => setClassifying(selectedEvents)}
              className="min-h-12 rounded-lg bg-blue-700 px-4 text-lg font-semibold text-white"
            >
              {t("table.bulk", { count: selected.size })}
            </button>
          )}
          {exportError && <p role="alert" className="text-lg text-red-700">{t("table.exportFailed")}</p>}
        </div>
        {events.data && (
          <DowntimeEventsTable
            events={events.data.results}
            total={events.data.count}
            offset={offset}
            limit={PAGE_SIZE}
            zone={zone}
            ordering={ordering}
            permissions={permissions}
            selected={selected}
            onToggle={(id) =>
              setSelected((current) => {
                const next = new Set(current);
                if (next.has(id)) next.delete(id);
                else next.add(id);
                return next;
              })
            }
            onToggleAll={(ids) =>
              setSelected((current) =>
                ids.every((id) => current.has(id)) ? new Set() : new Set([...current, ...ids]),
              )
            }
            onSort={setOrdering}
            onPage={setOffset}
            onClassify={(event: AnalysedDowntimeEvent) => setClassifying([event])}
            onOpenIncident={setDrawer}
          />
        )}
      </Panel>

      {classifying && factory.data && (
        <ClassifyPanel
          events={classifying}
          factoryId={factory.data.id}
          zone={zone}
          onClose={() => setClassifying(null)}
          onSaved={() => setSelected(new Set())}
        />
      )}
      {drawer !== null && <IncidentDrawer incidentId={drawer} zone={zone} onClose={() => setDrawer(null)} />}
    </main>
  );
}
