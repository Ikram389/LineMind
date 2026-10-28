import type { Reason } from "../../api/analysisTypes.ts";
import type { LineMachine } from "../../api/downtime.ts";
import type { MessageKey } from "../../i18n/en.ts";
import { t } from "../../i18n/t.ts";
import type { DowntimeFilters } from "../../lib/downtimeFilters.ts";
import type { QuickRange } from "../../lib/quickRanges.ts";
import { Button } from "../ui/Button.tsx";
import { SegmentedControl } from "../ui/Choice.tsx";
import { CheckboxField, Field, controlClass } from "../ui/Field.tsx";
import { FilterBar as Bar } from "../ui/FilterBar.tsx";

const QUICK: { key: QuickRange; label: MessageKey }[] = [
  { key: "currentShift", label: "filters.currentShift" },
  { key: "lastShift", label: "filters.lastShift" },
  { key: "today", label: "filters.today" },
  { key: "yesterday", label: "filters.yesterday" },
  { key: "last7", label: "filters.last7" },
];

const CATEGORIES: { value: string; label: MessageKey }[] = [
  { value: "breakdown", label: "category.breakdown" },
  { value: "blocked", label: "category.blocked" },
  { value: "starved", label: "category.starved" },
  { value: "planned", label: "category.planned" },
  { value: "no_data", label: "category.no_data" },
];

const MIN_DURATIONS = [0, 30, 60, 300, 900];

interface FilterBarProps {
  filters: DowntimeFilters;
  onChange: (patch: Partial<DowntimeFilters>) => void;
  onQuickRange: (range: QuickRange) => void;
  machines: LineMachine[];
  reasons: Reason[];
  /** datetime-local values in the factory's timezone */
  startLocal: string;
  endLocal: string;
  onLocalRange: (startLocal: string, endLocal: string) => void;
}

/** Range and view always visible; the other filters under "More filters". */
export function FilterBar({
  filters,
  onChange,
  onQuickRange,
  machines,
  reasons,
  startLocal,
  endLocal,
  onLocalRange,
}: FilterBarProps) {
  const advanced =
    filters.machine !== null ||
    filters.category !== null ||
    filters.reason !== null ||
    filters.classified !== null ||
    filters.minDuration !== null ||
    filters.includePlanned ||
    filters.includeNoData;

  return (
    <Bar
        moreActive={advanced}
        more={
          <>
            <Field label={t("filters.machine")}>
              {(props) => (
                <select
                  {...props}
                  value={filters.machine ?? ""}
                  onChange={(e) => onChange({ machine: e.target.value ? Number(e.target.value) : null })}
                  className={controlClass}
                >
                  <option value="">{t("filters.all")}</option>
                  {machines.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.external_id} {m.name}
                    </option>
                  ))}
                </select>
              )}
            </Field>
            <Field label={t("filters.category")}>
              {(props) => (
                <select
                  {...props}
                  value={filters.category ?? ""}
                  onChange={(e) => onChange({ category: e.target.value || null })}
                  className={controlClass}
                >
                  <option value="">{t("filters.all")}</option>
                  {CATEGORIES.map((c) => (
                    <option key={c.value} value={c.value}>
                      {t(c.label)}
                    </option>
                  ))}
                </select>
              )}
            </Field>
            <Field label={t("filters.reason")}>
              {(props) => (
                <select
                  {...props}
                  value={filters.reason ?? ""}
                  onChange={(e) => onChange({ reason: e.target.value || null })}
                  className={controlClass}
                >
                  <option value="">{t("filters.all")}</option>
                  <option value="unclassified">{t("filters.onlyUnclassified")}</option>
                  {reasons.map((r) => (
                    <option key={r.id} value={r.code}>
                      {r.code} · {r.name}
                    </option>
                  ))}
                </select>
              )}
            </Field>
            <Field label={t("filters.classified")}>
              {(props) => (
                <select
                  {...props}
                  value={filters.classified ?? ""}
                  onChange={(e) =>
                    onChange({ classified: (e.target.value || null) as DowntimeFilters["classified"] })
                  }
                  className={controlClass}
                >
                  <option value="">{t("filters.all")}</option>
                  <option value="true">{t("filters.onlyClassified")}</option>
                  <option value="false">{t("filters.onlyUnclassified")}</option>
                </select>
              )}
            </Field>
            <Field label={t("filters.minDuration")}>
              {(props) => (
                <select
                  {...props}
                  value={filters.minDuration ?? 0}
                  onChange={(e) => onChange({ minDuration: Number(e.target.value) || null })}
                  className={controlClass}
                >
                  {MIN_DURATIONS.map((s) => (
                    <option key={s} value={s}>
                      {s === 0 ? t("filters.anyDuration") : s < 60 ? `${s} s` : `${s / 60} min`}
                    </option>
                  ))}
                </select>
              )}
            </Field>
            <div className="flex flex-col">
              <CheckboxField
                label={t("filters.includePlanned")}
                checked={filters.includePlanned}
                onChange={(includePlanned) => onChange({ includePlanned })}
              />
              <CheckboxField
                label={t("filters.includeNoData")}
                checked={filters.includeNoData}
                onChange={(includeNoData) => onChange({ includeNoData })}
              />
            </div>
            <Button
              variant="ghost"
              onClick={() =>
                onChange({
                  machine: null,
                  category: null,
                  reason: null,
                  alarm: null,
                  classified: null,
                  minDuration: null,
                  includePlanned: false,
                  includeNoData: false,
                })
              }
            >
              {t("filters.clear")}
            </Button>
          </>
        }
      >
        <div role="group" aria-label={t("filters.quickRanges")} className="flex w-full flex-wrap gap-2">
          {QUICK.map((q) => (
            <Button key={q.key} onClick={() => onQuickRange(q.key)}>
              {t(q.label)}
            </Button>
          ))}
        </div>
        <Field label={t("filters.from")}>
          {(props) => (
            <input
              {...props}
              type="datetime-local"
              value={startLocal}
              onChange={(e) => onLocalRange(e.target.value, endLocal)}
              className={controlClass}
            />
          )}
        </Field>
        <Field label={t("filters.to")}>
          {(props) => (
            <input
              {...props}
              type="datetime-local"
              value={endLocal}
              onChange={(e) => onLocalRange(startLocal, e.target.value)}
              className={controlClass}
            />
          )}
        </Field>
        <div className="flex flex-col gap-1">
          <span className="text-small font-semibold text-ink-muted">{t("filters.view")}</span>
          <SegmentedControl
            label={t("filters.view")}
            value={filters.view}
            onChange={(view) => onChange({ view })}
            options={[
              { value: "line", label: t("filters.lineViewShort") },
              { value: "machine", label: t("filters.machineViewShort") },
            ]}
          />
          <span className="text-small text-ink-muted">
            {t(filters.view === "line" ? "filters.lineView" : "filters.machineView")}
          </span>
        </div>
    </Bar>
  );
}
