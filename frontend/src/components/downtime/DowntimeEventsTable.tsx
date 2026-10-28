import { Clock } from "lucide-react";

import type { AnalysedDowntimeEvent } from "../../api/analysisTypes.ts";
import { t } from "../../i18n/t.ts";
import type { Permissions } from "../../lib/permissions.ts";
import { formatDateTime, formatDuration } from "../../lib/time.ts";
import { Button } from "../ui/Button.tsx";
import { type Column, DataTable, type Sort } from "../ui/DataTable.tsx";
import { EmptyState } from "../ui/Feedback.tsx";
import { Tag } from "../ui/Tag.tsx";
import { CategoryBadge, RoleBadge } from "./badges.tsx";

interface DowntimeEventsTableProps {
  events: AnalysedDowntimeEvent[];
  total: number;
  offset: number;
  limit: number;
  zone: string;
  /** Server ordering, e.g. "-started_at". */
  ordering: string;
  permissions: Permissions;
  selected: Set<number>;
  onToggle: (id: number) => void;
  onToggleAll: (ids: number[]) => void;
  onSort: (ordering: string) => void;
  onPage: (offset: number) => void;
  onClassify: (event: AnalysedDowntimeEvent) => void;
  onOpenIncident: (incidentId: number) => void;
}

function toSort(ordering: string): Sort {
  return ordering.startsWith("-")
    ? { key: ordering.slice(1), direction: "desc" }
    : { key: ordering, direction: "asc" };
}

export function DowntimeEventsTable({
  events,
  total,
  offset,
  limit,
  zone,
  ordering,
  permissions,
  selected,
  onToggle,
  onToggleAll,
  onSort,
  onPage,
  onClassify,
  onOpenIncident,
}: DowntimeEventsTableProps) {
  const columns: Column<AnalysedDowntimeEvent>[] = [
    {
      key: "started_at",
      header: t("table.start"),
      sortable: true,
      render: (e) => <span className="whitespace-nowrap tabular-nums">{formatDateTime(e.started_at, zone)}</span>,
    },
    { key: "machine", header: t("table.machine"), sortable: true, render: (e) => e.machine.name },
    {
      key: "duration",
      header: t("table.duration"),
      sortable: true,
      render: (e) => (
        <span className="inline-flex flex-wrap items-center gap-1 whitespace-nowrap tabular-nums">
          {formatDuration(e.clipped_duration_seconds ?? e.duration_seconds)}
          {e.is_ongoing && (
            <Tag tone="critical" icon={Clock}>
              {t("detail.ongoing")}
            </Tag>
          )}
        </span>
      ),
    },
    {
      key: "category",
      header: t("table.category"),
      render: (e) => (
        <span className="inline-flex flex-wrap items-center gap-1">
          <CategoryBadge category={e.category} />
          {e.alarm_code && <span className="text-small text-ink-muted">{e.alarm_code}</span>}
        </span>
      ),
    },
    {
      key: "reason",
      header: t("table.reason"),
      // Who classified it, under the reason: one column less, so the action stays in view.
      render: (e) =>
        e.classification ? (
          <span className="flex flex-col">
            <span>{e.classification.reason.name}</span>
            <span className="max-w-56 truncate text-small text-ink-muted" title={e.classification.created_by ?? ""}>
              {e.classification.created_by && `${t("table.classifiedBy")}: ${e.classification.created_by}`}
            </span>
          </span>
        ) : (
          <span className="text-ink-muted">{t("detail.notClassified")}</span>
        ),
    },
    {
      key: "role",
      header: `${t("table.role")} · ${t("table.incident")}`,
      // The line stop it belongs to, under its role: one column less.
      render: (e) => (
        <span className="flex flex-col items-start gap-0.5 whitespace-nowrap">
          <RoleBadge role={e.role_in_incident} />
          {e.incident !== null && (
            <button
              type="button"
              onClick={() => onOpenIncident(e.incident as number)}
              aria-label={t("drawer.title", { id: e.incident })}
              className="min-h-11 rounded-control px-1 font-semibold text-accent underline hover:bg-accent-soft"
            >
              #{e.incident}
            </button>
          )}
        </span>
      ),
    },
  ];
  if (permissions.canClassify) {
    columns.push({
      key: "actions",
      stickyEnd: true,
      header: <span className="sr-only">{t("table.classify")}</span>,
      render: (e) => (
        <Button onClick={() => onClassify(e)}>
          {e.classification ? t("table.reclassify") : t("table.classify")}
        </Button>
      ),
    });
  }

  return (
    <DataTable
      columns={columns}
      rows={events}
      rowKey={(e) => e.id}
      rowTestId={(e) => `event-row-${e.id}`}
      caption={t("table.title")}
      sort={toSort(ordering)}
      onSort={(sort) => onSort(sort.direction === "desc" ? `-${sort.key}` : sort.key)}
      pagination={{ total, offset, limit, onPage }}
      empty={<EmptyState title={t("table.empty")} />}
      selection={
        permissions.canBulkClassify
          ? {
              isSelected: (e) => selected.has(e.id),
              onToggle: (e) => onToggle(e.id),
              onToggleAll: (rows) => onToggleAll(rows.map((e) => e.id)),
              rowLabel: (e) => t("table.select", { machine: e.machine.name, time: formatDateTime(e.started_at, zone) }),
              allLabel: t("table.selectAll"),
            }
          : undefined
      }
    />
  );
}
