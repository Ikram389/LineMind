import type { ParetoGroupBy, ParetoResponse } from "../../api/analysisTypes.ts";
import type { MessageKey } from "../../i18n/en.ts";
import { t } from "../../i18n/t.ts";
import { cn } from "../../lib/cn.ts";
import { formatDuration } from "../../lib/time.ts";
import { Card } from "../ui/Card.tsx";
import { SegmentedControl } from "../ui/Choice.tsx";
import { EmptyState } from "../ui/Feedback.tsx";
import { ParetoChart } from "../ui/ParetoChart.tsx";
import { Tag } from "../ui/Tag.tsx";

const GROUPS: { key: ParetoGroupBy; label: MessageKey }[] = [
  { key: "reason", label: "pareto.byReason" },
  { key: "machine", label: "pareto.byMachine" },
  { key: "category", label: "pareto.byCategory" },
  { key: "alarm_code", label: "pareto.byAlarm" },
];

interface ParetoPanelProps {
  pareto: ParetoResponse;
  groupBy: ParetoGroupBy;
  onGroupBy: (group: ParetoGroupBy) => void;
  onSelectGroup: (key: string) => void;
  selectedKey: string | null;
}

/** Where the time was lost: the chart, and the same groups as buttons that filter the table. */
export function ParetoPanel({ pareto, groupBy, onGroupBy, onSelectGroup, selectedKey }: ParetoPanelProps) {
  const rows = pareto.groups.map((g) => ({
    key: g.key,
    label: g.label,
    value: Math.round((g.total_seconds / 60) * 10) / 10,
    cumulative: Math.round(g.cumulative_share * 1000) / 10,
  }));

  return (
    <Card
      title={
        <span className="flex flex-wrap items-center gap-2">
          {t("pareto.title")}
          <Tag tone={pareto.view === "line" ? "accent" : "neutral"} data-testid="pareto-view">
            {t(pareto.view === "line" ? "pareto.lineView" : "pareto.machineView")}
          </Tag>
        </span>
      }
      actions={
        <SegmentedControl
          label={t("pareto.groupBy")}
          value={groupBy}
          onChange={onGroupBy}
          options={GROUPS.map((g) => ({ value: g.key, label: t(g.label) }))}
        />
      }
    >
      <p className="mb-3 text-small text-ink-muted">{pareto.view_note}</p>
      {rows.length === 0 ? (
        <EmptyState title={t("pareto.empty")} />
      ) : (
        <>
          <ParetoChart
            rows={rows}
            valueLabel={t("pareto.duration")}
            cumulativeLabel={t("pareto.cumulative")}
            ariaLabel={t("pareto.chart")}
            selectedKey={selectedKey}
            onSelect={onSelectGroup}
          />
          <p className="mt-3 text-small text-ink-muted">{t("pareto.filterHint")}</p>
          <ul className="mt-2 flex flex-wrap gap-2">
            {pareto.groups.map((g) => (
              <li key={g.key}>
                <button
                  type="button"
                  aria-pressed={selectedKey === g.key}
                  onClick={() => onSelectGroup(g.key)}
                  data-testid={`pareto-group-${g.key}`}
                  className={cn(
                    "min-h-11 rounded-control border px-3 text-left text-small",
                    selectedKey === g.key
                      ? "border-accent bg-accent-soft font-semibold text-accent"
                      : "border-line-strong text-ink hover:bg-surface-muted",
                  )}
                >
                  {t("pareto.row", {
                    label: g.label,
                    duration: formatDuration(g.total_seconds),
                    count: g.occurrences,
                    share: (g.share * 100).toFixed(1),
                  })}
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </Card>
  );
}
