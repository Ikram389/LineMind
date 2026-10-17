import type { OeeResult, Ratio } from "../api/types.ts";
import type { MessageKey } from "../i18n/en.ts";
import { t } from "../i18n/t.ts";
import { cn } from "../lib/cn.ts";
import { InlineNotice } from "./ui/Feedback.tsx";

function Figure({ label, ratio, large = false }: { label: MessageKey; ratio: Ratio; large?: boolean }) {
  const value = ratio.percent === null ? t("oee.notAvailable") : `${ratio.percent.toFixed(1)}%`;
  return (
    <div className={cn("min-w-0", large && "col-span-3 sm:col-span-1 sm:border-r sm:border-line sm:pr-6")}>
      <p className="text-small font-semibold text-ink-muted">{t(label)}</p>
      <p
        className={cn("font-bold tabular-nums text-ink", large ? "text-hero" : "text-page")}
        title={ratio.null_reason ?? undefined}
      >
        {value}
      </p>
      {ratio.percent === null && ratio.null_reason && <p className="text-small text-ink-muted">{ratio.null_reason}</p>}
    </div>
  );
}

/** The four OEE results, data coverage and the API's warnings as readable messages. */
export function OeePanel({ result }: { result: OeeResult }) {
  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-3 items-end gap-4 sm:grid-cols-[auto_repeat(3,minmax(0,1fr))] sm:gap-6">
        <Figure label="oee.oee" ratio={result.oee} large />
        <Figure label="oee.availability" ratio={result.availability} />
        <Figure label="oee.performance" ratio={result.performance} />
        <Figure label="oee.quality" ratio={result.quality} />
      </div>
      <p className="text-small text-ink-muted">
        {t("oee.coverage")}:{" "}
        <span className="font-semibold tabular-nums text-ink">
          {result.data_coverage.percent === null
            ? t("oee.notAvailable")
            : `${result.data_coverage.percent.toFixed(0)}%`}
        </span>
      </p>
      {result.null_reason && <p className="text-body text-ink-muted">{result.null_reason}</p>}
      {result.warnings.length > 0 && (
        <ul aria-label={t("oee.warnings")} className="flex flex-col gap-2">
          {result.warnings.map((warning) => (
            <li key={warning.code} data-code={warning.code}>
              <InlineNotice tone="warning">{warning.message}</InlineNotice>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
