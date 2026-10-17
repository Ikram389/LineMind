import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";

import { getShiftQuality } from "../../api/quality.ts";
import { queryKeys } from "../../api/queryKeys.ts";
import type { CurrentShift } from "../../api/types.ts";
import { t } from "../../i18n/t.ts";
import { formatCount, formatRate } from "../../lib/qualityFormat.ts";
import { Panel } from "../Panel.tsx";
import { buttonClass } from "../ui/buttonClass.ts";

const REFRESH_MS = 60_000; // a safety net: quality_updated messages are throttled

/** The overview's compact quality card; live messages write into the same cache entry. */
export function QualityCard({ lineId, shift }: { lineId: number; shift: CurrentShift | null | undefined }) {
  const quality = useQuery({
    queryKey: queryKeys.shiftQuality(lineId),
    queryFn: () => getShiftQuality(lineId, shift ?? null),
    enabled: shift !== undefined,
    refetchInterval: REFRESH_MS,
  });
  const data = quality.data;

  return (
    <Panel
      title={t("qcard.title")}
      isLoading={quality.isLoading && shift !== undefined}
      isError={quality.isError && !data}
      isEmpty={data?.shift === null}
      emptyText={t("qcard.noShift")}
    >
      {data && (
        <div className="flex flex-wrap items-end justify-between gap-4">
          <dl className="grid grid-cols-3 gap-6">
            <div>
              <dt className="text-small font-semibold text-ink-muted">{t("qcard.rate")}</dt>
              <dd className="text-stat font-bold tabular-nums text-ink" data-testid="qcard-rate">
                {formatRate(data.defect_rate)}
              </dd>
            </div>
            <div>
              <dt className="text-small font-semibold text-ink-muted">{t("qcard.defects")}</dt>
              <dd className="text-stat font-bold tabular-nums text-ink" data-testid="qcard-defects">
                {formatCount(data.defects)}
              </dd>
            </div>
            <div>
              <dt className="text-small font-semibold text-ink-muted">{t("qcard.unreviewed")}</dt>
              <dd className="text-stat font-bold tabular-nums text-ink" data-testid="qcard-unreviewed">
                {formatCount(data.unreviewed)}
              </dd>
            </div>
          </dl>
          <Link
            to={`/lines/${lineId}/quality`}
            className={buttonClass("secondary")}
          >
            {t("qcard.open")}
          </Link>
        </div>
      )}
    </Panel>
  );
}
