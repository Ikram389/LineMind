import type { Reason } from "../../api/analysisTypes.ts";
import type { LineMachine } from "../../api/downtime.ts";
import type { MessageKey } from "../../i18n/en.ts";
import { t } from "../../i18n/t.ts";
import type { DowntimeFilters } from "../../lib/downtimeFilters.ts";

import type { QuickRange } from "../../lib/quickRanges.ts";

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

const select = "rounded-lg border border-gray-300 bg-white px-3 py-2 text-lg";

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
  return (
    <section className="flex flex-col gap-3 rounded-xl bg-white p-4 shadow-sm" aria-label="Filters">
      <div className="flex flex-wrap gap-2">
        {QUICK.map((q) => (
          <button
            key={q.key}
            type="button"
            onClick={() => onQuickRange(q.key)}
            className="min-h-12 rounded-lg border-2 border-gray-300 px-4 text-lg font-semibold hover:bg-gray-100"
          >
            {t(q.label)}
          </button>
        ))}
        <label className="flex items-center gap-2 text-lg">
          {t("filters.from")}
          <input
            type="datetime-local"
            value={startLocal}
            onChange={(e) => onLocalRange(e.target.value, endLocal)}
            className={select}
          />
        </label>
        <label className="flex items-center gap-2 text-lg">
          {t("filters.to")}
          <input
            type="datetime-local"
            value={endLocal}
            onChange={(e) => onLocalRange(startLocal, e.target.value)}
            className={select}
          />
        </label>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 text-lg">
          {t("filters.machine")}
          <select
            value={filters.machine ?? ""}
            onChange={(e) => onChange({ machine: e.target.value ? Number(e.target.value) : null })}
            className={select}
          >
            <option value="">{t("filters.all")}</option>
            {machines.map((m) => (
              <option key={m.id} value={m.id}>
                {m.external_id} {m.name}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-2 text-lg">
          {t("filters.category")}
          <select
            value={filters.category ?? ""}
            onChange={(e) => onChange({ category: e.target.value || null })}
            className={select}
          >
            <option value="">{t("filters.all")}</option>
            {CATEGORIES.map((c) => (
              <option key={c.value} value={c.value}>
                {t(c.label)}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-2 text-lg">
          {t("filters.reason")}
          <select
            value={filters.reason ?? ""}
            onChange={(e) => onChange({ reason: e.target.value || null })}
            className={select}
          >
            <option value="">{t("filters.all")}</option>
            <option value="unclassified">{t("filters.onlyUnclassified")}</option>
            {reasons.map((r) => (
              <option key={r.id} value={r.code}>
                {r.code} · {r.name}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-2 text-lg">
          {t("filters.classified")}
          <select
            value={filters.classified ?? ""}
            onChange={(e) =>
              onChange({ classified: (e.target.value || null) as DowntimeFilters["classified"] })
            }
            className={select}
          >
            <option value="">{t("filters.all")}</option>
            <option value="true">{t("filters.onlyClassified")}</option>
            <option value="false">{t("filters.onlyUnclassified")}</option>
          </select>
        </label>
        <label className="flex items-center gap-2 text-lg">
          {t("filters.minDuration")}
          <select
            value={filters.minDuration ?? 0}
            onChange={(e) => onChange({ minDuration: Number(e.target.value) || null })}
            className={select}
          >
            {MIN_DURATIONS.map((s) => (
              <option key={s} value={s}>
                {s === 0 ? t("filters.anyDuration") : s < 60 ? `${s} s` : `${s / 60} min`}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-2 text-lg">
          <input
            type="checkbox"
            checked={filters.includePlanned}
            onChange={(e) => onChange({ includePlanned: e.target.checked })}
            className="h-6 w-6"
          />
          {t("filters.includePlanned")}
        </label>
        <label className="flex items-center gap-2 text-lg">
          <input
            type="checkbox"
            checked={filters.includeNoData}
            onChange={(e) => onChange({ includeNoData: e.target.checked })}
            className="h-6 w-6"
          />
          {t("filters.includeNoData")}
        </label>
      </div>

      <fieldset className="flex flex-wrap items-center gap-4">
        <legend className="sr-only">{t("filters.view")}</legend>
        {(["line", "machine"] as const).map((view) => (
          <label
            key={view}
            className={`flex min-h-12 cursor-pointer items-center gap-2 rounded-lg border-2 px-4 text-lg ${
              filters.view === view ? "border-blue-700 bg-blue-50 font-semibold" : "border-gray-300"
            }`}
          >
            <input
              type="radio"
              name="view"
              value={view}
              checked={filters.view === view}
              onChange={() => onChange({ view })}
              className="h-5 w-5"
            />
            {t(view === "line" ? "filters.lineView" : "filters.machineView")}
          </label>
        ))}
        <button
          type="button"
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
          className="ml-auto text-lg text-blue-800 underline"
        >
          {t("filters.clear")}
        </button>
      </fieldset>
    </section>
  );
}
