import { Info } from "lucide-react";

import type { OeeResult, Ratio } from "../api/types.ts";
import type { MessageKey } from "../i18n/en.ts";
import { t } from "../i18n/t.ts";

function Figure({ label, ratio, large = false }: { label: MessageKey; ratio: Ratio; large?: boolean }) {
  const value = ratio.percent === null ? t("oee.notAvailable") : `${ratio.percent.toFixed(1)}%`;
  return (
    <div>
      <p className="text-lg text-gray-600">{t(label)}</p>
      <p
        className={`font-extrabold tabular-nums text-gray-900 ${large ? "text-6xl" : "text-4xl"}`}
        title={ratio.null_reason ?? undefined}
      >
        {value}
      </p>
      {ratio.percent === null && ratio.null_reason && (
        <p className="text-sm text-gray-500">{ratio.null_reason}</p>
      )}
    </div>
  );
}

/** The four OEE results, data coverage and the API's warnings as readable messages. */
export function OeePanel({ result }: { result: OeeResult }) {
  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <Figure label="oee.oee" ratio={result.oee} large />
        <Figure label="oee.availability" ratio={result.availability} />
        <Figure label="oee.performance" ratio={result.performance} />
        <Figure label="oee.quality" ratio={result.quality} />
      </div>
      <p className="text-lg text-gray-700">
        {t("oee.coverage")}:{" "}
        <span className="font-semibold tabular-nums">
          {result.data_coverage.percent === null
            ? t("oee.notAvailable")
            : `${result.data_coverage.percent.toFixed(0)}%`}
        </span>
      </p>
      {result.null_reason && <p className="text-lg text-gray-600">{result.null_reason}</p>}
      {result.warnings.length > 0 && (
        <ul aria-label={t("oee.warnings")} className="flex flex-col gap-2">
          {result.warnings.map((warning) => (
            <li
              key={warning.code}
              data-code={warning.code}
              className="flex items-start gap-2 rounded-md bg-amber-50 p-2 text-base text-amber-900"
            >
              <Info aria-hidden className="mt-0.5 h-5 w-5 shrink-0" />
              <span>{warning.message}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
