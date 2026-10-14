import type { ProductSummary } from "../../api/quality.ts";
import { type DefectType, type InspectionStation, SEVERITIES } from "../../api/qualityTypes.ts";
import type { MessageKey } from "../../i18n/en.ts";
import { t } from "../../i18n/t.ts";
import type { QualityFilters } from "../../lib/qualityFilters.ts";
import type { QuickRange } from "../../lib/quickRanges.ts";

const QUICK: { key: QuickRange; label: MessageKey }[] = [
  { key: "currentShift", label: "filters.currentShift" },
  { key: "lastShift", label: "filters.lastShift" },
  { key: "today", label: "filters.today" },
  { key: "yesterday", label: "filters.yesterday" },
  { key: "last7", label: "filters.last7" },
];

interface QualityFilterBarProps {
  filters: QualityFilters;
  onChange: (patch: Partial<QualityFilters>) => void;
  onQuickRange: (range: QuickRange) => void;
  stations: InspectionStation[];
  defectTypes: DefectType[];
  products: ProductSummary[];
  /** datetime-local values in the factory's timezone */
  startLocal: string;
  endLocal: string;
  onLocalRange: (startLocal: string, endLocal: string) => void;
}

const select = "rounded-lg border border-gray-300 bg-white px-3 py-2 text-lg";
const num = (value: string): number | null => (value ? Number(value) : null);

/** The same layout as the downtime filter bar; every choice is kept in the URL. */
export function QualityFilterBar({
  filters,
  onChange,
  onQuickRange,
  stations,
  defectTypes,
  products,
  startLocal,
  endLocal,
  onLocalRange,
}: QualityFilterBarProps) {
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
          {t("qfilters.station")}
          <select
            value={filters.station ?? ""}
            onChange={(e) => onChange({ station: num(e.target.value) })}
            className={select}
          >
            <option value="">{t("filters.all")}</option>
            {stations.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-2 text-lg">
          {t("qfilters.defectType")}
          <select
            value={filters.defectType ?? ""}
            onChange={(e) => onChange({ defectType: e.target.value || null })}
            className={select}
          >
            <option value="">{t("filters.all")}</option>
            {defectTypes.map((d) => (
              <option key={d.id} value={d.code}>
                {d.code} · {d.name}
              </option>
            ))}
            <option value="unknown">{t("qfilters.unknownType")}</option>
          </select>
        </label>
        <label className="flex items-center gap-2 text-lg">
          {t("qfilters.severity")}
          <select
            value={filters.severity ?? ""}
            onChange={(e) =>
              onChange({ severity: (e.target.value || null) as QualityFilters["severity"] })
            }
            className={select}
          >
            <option value="">{t("filters.all")}</option>
            {SEVERITIES.map((s) => (
              <option key={s} value={s}>
                {t(`severity.${s}`)}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-2 text-lg">
          {t("qfilters.product")}
          <select
            value={filters.product ?? ""}
            onChange={(e) => onChange({ product: num(e.target.value) })}
            className={select}
          >
            <option value="">{t("filters.all")}</option>
            {products.map((p) => (
              <option key={p.id} value={p.id}>
                {p.sku} · {p.name}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-2 text-lg">
          {t("qfilters.review")}
          <select
            value={filters.reviewed ?? ""}
            onChange={(e) =>
              onChange({ reviewed: (e.target.value || null) as QualityFilters["reviewed"] })
            }
            className={select}
          >
            <option value="">{t("filters.all")}</option>
            <option value="false">{t("qfilters.unreviewed")}</option>
            <option value="true">{t("qfilters.reviewed")}</option>
          </select>
        </label>
        <button
          type="button"
          onClick={() =>
            onChange({ station: null, machine: null, defectType: null, severity: null, product: null, reviewed: null })
          }
          className="min-h-12 rounded-lg px-4 text-lg text-blue-800 underline"
        >
          {t("filters.clear")}
        </button>
      </div>
    </section>
  );
}
