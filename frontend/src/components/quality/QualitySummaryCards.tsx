import type { QualitySummary } from "../../api/qualityTypes.ts";
import { t } from "../../i18n/t.ts";
import { formatCount, formatRate } from "../../lib/qualityFormat.ts";

function Card({ label, value, sub, testId }: { label: string; value: string; sub?: string; testId?: string }) {
  return (
    <div className="rounded-xl bg-white p-4 shadow-sm" data-testid={testId}>
      <p className="text-lg text-gray-600">{label}</p>
      <p className="text-4xl font-extrabold tabular-nums text-gray-900">{value}</p>
      {sub && <p className="text-base text-gray-600">{sub}</p>}
    </div>
  );
}

/** Inspected · Defects · Defect rate · Not reviewed, then volumes per station. */
export function QualitySummaryCards({ summary }: { summary: QualitySummary }) {
  const inspected = Math.max(0, ...summary.inspected_by_station.map((s) => s.inspected));
  const severity = summary.defects_by_severity;
  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Card
          label={t("qsummary.inspected")}
          value={formatCount(summary.line_total_count)}
          sub={t("qsummary.inspectedSub", { count: formatCount(inspected) })}
          testId="quality-inspected"
        />
        <Card
          label={t("qsummary.defects")}
          value={formatCount(summary.defects)}
          sub={t("qsummary.bySeverity", {
            critical: severity.critical,
            major: severity.major,
            minor: severity.minor,
          })}
          testId="quality-defects"
        />
        <Card
          label={t("qsummary.rate")}
          value={formatRate(summary.defect_rate)}
          sub={t("qsummary.rateSub", { total: formatCount(summary.line_total_count) })}
          testId="quality-rate"
        />
        <Card label={t("qsummary.unreviewed")} value={formatCount(summary.unreviewed)} testId="quality-unreviewed" />
      </div>
      {summary.false_rejects > 0 && (
        <p className="rounded-lg bg-blue-50 p-2 text-lg text-blue-900">
          {t("qsummary.falseRejects", { count: summary.false_rejects })}
        </p>
      )}
      {summary.results_with_warnings > 0 && (
        <p className="rounded-lg bg-amber-50 p-2 text-lg text-amber-900" role="note">
          {t("qsummary.warnings", {
            count: summary.results_with_warnings,
            examples: summary.warnings.slice(0, 2).join(" "),
          })}
        </p>
      )}
      <details className="rounded-xl bg-white p-3 shadow-sm">
        <summary className="cursor-pointer text-lg font-semibold">{t("qsummary.stations")}</summary>
        <ul className="mt-2 flex flex-col gap-1 text-lg">
          {summary.inspected_by_station.map((s) => (
            <li key={s.station.id}>
              {t("qsummary.stationRow", {
                station: s.station.name,
                defects: formatCount(s.defects),
                inspected: formatCount(s.inspected),
                rate: formatRate(s.defect_rate),
              })}
            </li>
          ))}
        </ul>
      </details>
    </div>
  );
}
