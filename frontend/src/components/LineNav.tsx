import { useQuery } from "@tanstack/react-query";
import { CircleAlert } from "lucide-react";
import { NavLink } from "react-router";

import { countUnclassified } from "../api/downtime.ts";
import { queryKeys } from "../api/queryKeys.ts";
import type { CurrentShift } from "../api/types.ts";
import { t } from "../i18n/t.ts";
import { usePermissions } from "../lib/permissions.ts";

interface LineNavProps {
  lineId: number;
  shift: CurrentShift | null | undefined;
}

const tab = ({ isActive }: { isActive: boolean }) =>
  `rounded-lg px-5 py-3 text-xl font-semibold ${
    isActive ? "bg-gray-900 text-white" : "bg-white text-gray-800 hover:bg-gray-200"
  }`;

/** "Unclassified N": a link to the stops of this shift that still need a reason. */
export function UnclassifiedBadge({ lineId, shift }: LineNavProps) {
  const unclassified = useQuery({
    queryKey: [...queryKeys.unclassified(lineId), shift?.start],
    queryFn: () => countUnclassified(lineId, shift as CurrentShift),
    enabled: Boolean(shift),
    refetchInterval: 60_000,
  });
  const count = unclassified.data ?? 0;
  if (count === 0) return null;
  return (
    <NavLink
      to={`/lines/${lineId}/unclassified`}
      data-testid="unclassified-badge"
      aria-label={t("nav.unclassifiedLabel", { count })}
      className="inline-flex min-h-11 items-center gap-2 rounded-full border border-warning bg-warning-soft px-4 text-body font-bold text-warning"
    >
      <CircleAlert aria-hidden className="h-5 w-5" />
      {t("nav.unclassified", { count })}
    </NavLink>
  );
}

/** Overview · Downtime · Quality · Reasons and Quality setup (managers), plus the
 * "stops needing a reason" badge. */
export function LineNav({ lineId, shift }: LineNavProps) {
  const { canManageReasons, canManageQuality } = usePermissions();

  return (
    <nav className="flex flex-wrap items-center gap-2" aria-label="Line pages">
      <NavLink to={`/lines/${lineId}`} end className={tab}>
        {t("nav.overview")}
      </NavLink>
      <NavLink to={`/lines/${lineId}/downtime`} className={tab}>
        {t("nav.downtime")}
      </NavLink>
      <NavLink to={`/lines/${lineId}/quality`} className={tab}>
        {t("nav.quality")}
      </NavLink>
      {canManageReasons && (
        <NavLink to={`/lines/${lineId}/reasons`} className={tab}>
          {t("nav.reasons")}
        </NavLink>
      )}
      {canManageQuality && (
        <NavLink to={`/lines/${lineId}/quality-setup`} className={tab}>
          {t("nav.qualitySetup")}
        </NavLink>
      )}
      <span className="ml-auto">
        <UnclassifiedBadge lineId={lineId} shift={shift} />
      </span>
    </nav>
  );
}
