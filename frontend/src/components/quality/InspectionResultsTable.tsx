import type { InspectionResult } from "../../api/qualityTypes.ts";
import type { MessageKey } from "../../i18n/en.ts";
import { t } from "../../i18n/t.ts";
import { reviewLabel } from "../../lib/qualityFormat.ts";
import { formatDateTime } from "../../lib/time.ts";

interface InspectionResultsTableProps {
  results: InspectionResult[];
  total: number;
  offset: number;
  limit: number;
  zone: string;
  canReview: boolean;
  onPage: (offset: number) => void;
  onReview: (result: InspectionResult) => void;
  onOpenIncident: (incidentId: number) => void;
}

const SEVERITY_STYLE: Record<string, string> = {
  critical: "bg-red-100 text-red-900",
  major: "bg-orange-100 text-orange-900",
  minor: "bg-yellow-100 text-yellow-900",
};

function DefectCell({ result }: { result: InspectionResult }) {
  const detected = result.defect_type;
  const effective = result.effective_defect_type;
  return (
    <div className={result.is_defect ? "" : "text-gray-500 line-through"}>
      {detected ? `${detected.code} · ${detected.name}` : t("qtable.unknownType", { code: result.reported_code || "–" })}
      {effective && detected && effective.code !== detected.code && (
        <span className="ml-1 no-underline">→ {effective.code}</span>
      )}
      {result.warnings.length > 0 && (
        <p className="text-sm text-amber-800" title={result.warnings.join(" ")}>
          ⚠ {result.warnings[0]}
        </p>
      )}
    </div>
  );
}

function ContextCell({ result, onOpenIncident }: { result: InspectionResult; onOpenIncident: (id: number) => void }) {
  const context = result.context;
  if (!context) return <span>–</span>;
  const state = t(`state.${context.machine_state}` as MessageKey);
  return (
    <div className="flex flex-col gap-1">
      {context.incident && (
        <button
          type="button"
          onClick={() => context.incident && onOpenIncident(context.incident.id)}
          aria-label={t("qtable.openIncident", { id: context.incident.id })}
          className="text-left text-blue-800 underline"
          data-testid={`incident-link-${result.id}`}
        >
          {context.incident.text}
        </button>
      )}
      <span className="text-base text-gray-700">
        {t("qtable.machineContext", { machine: result.machine.name, state: state.toLowerCase() })}
        {context.last_alarm_code && ` · ${t("qtable.alarmContext", { code: context.last_alarm_code })}`}
      </span>
    </div>
  );
}

export function InspectionResultsTable({
  results,
  total,
  offset,
  limit,
  zone,
  canReview,
  onPage,
  onReview,
  onOpenIncident,
}: InspectionResultsTableProps) {
  if (results.length === 0) return <p className="text-lg text-gray-600">{t("qtable.empty")}</p>;
  const severity = (r: InspectionResult) => r.effective_defect_type?.severity ?? null;

  return (
    <div className="flex flex-col gap-3">
      <div className="overflow-x-auto">
        <table className="w-full text-left text-lg">
          <thead className="border-b-2 border-gray-300">
            <tr>
              <th className="p-2">{t("qtable.time")}</th>
              <th className="p-2">{t("qtable.station")}</th>
              <th className="p-2">{t("qtable.defect")}</th>
              <th className="p-2">{t("qtable.severity")}</th>
              <th className="p-2">{t("qtable.confidence")}</th>
              <th className="p-2">{t("qtable.review")}</th>
              <th className="p-2">{t("qtable.product")}</th>
              <th className="p-2">{t("qtable.context")}</th>
              <th className="p-2" />
            </tr>
          </thead>
          <tbody>
            {results.map((result) => {
              const sev = severity(result);
              return (
                <tr key={result.id} data-testid={`result-row-${result.id}`} className="border-b border-gray-100 align-top">
                  <td className="whitespace-nowrap p-2 tabular-nums">{formatDateTime(result.timestamp, zone)}</td>
                  <td className="p-2">
                    {result.station?.name ?? t("qtable.noStation", { machine: result.machine.name })}
                  </td>
                  <td className="p-2">
                    <DefectCell result={result} />
                  </td>
                  <td className="p-2">
                    <span className={`rounded px-2 py-1 text-base font-semibold ${sev ? SEVERITY_STYLE[sev] : "bg-gray-100"}`}>
                      {t(`severity.${sev ?? "unknown"}` as MessageKey)}
                    </span>
                  </td>
                  <td className="p-2 tabular-nums">
                    {result.confidence === null ? "–" : result.confidence.toFixed(2)}
                  </td>
                  <td className="p-2">{reviewLabel(result)}</td>
                  <td className="p-2">{result.context?.product?.sku ?? "–"}</td>
                  <td className="p-2">
                    <ContextCell result={result} onOpenIncident={onOpenIncident} />
                  </td>
                  <td className="p-2">
                    <button
                      type="button"
                      onClick={() => onReview(result)}
                      className={`min-h-11 rounded-lg px-4 font-semibold ${
                        canReview ? "bg-blue-700 text-white" : "border border-gray-400"
                      }`}
                    >
                      {canReview ? t("qtable.reviewButton") : t("qtable.details")}
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="flex items-center gap-3 text-lg">
        <button
          type="button"
          disabled={offset === 0}
          onClick={() => onPage(Math.max(0, offset - limit))}
          className="min-h-11 rounded-lg border border-gray-400 px-4 disabled:opacity-40"
        >
          {t("table.previous")}
        </button>
        <span>{t("table.page", { from: offset + 1, to: Math.min(offset + limit, total), total })}</span>
        <button
          type="button"
          disabled={offset + limit >= total}
          onClick={() => onPage(offset + limit)}
          className="min-h-11 rounded-lg border border-gray-400 px-4 disabled:opacity-40"
        >
          {t("table.next")}
        </button>
      </div>
    </div>
  );
}
