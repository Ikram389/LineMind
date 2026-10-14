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

/** Overview · Downtime · Quality · Reasons and Quality setup (managers), plus the
 * "stops needing a reason" badge. */
export function LineNav({ lineId, shift }: LineNavProps) {
  const { canManageReasons, canManageQuality } = usePermissions();
  const unclassified = useQuery({
    queryKey: [...queryKeys.unclassified(lineId), shift?.start],
    queryFn: () => countUnclassified(lineId, shift as CurrentShift),
    enabled: Boolean(shift),
    refetchInterval: 60_000,
  });
  const count = unclassified.data ?? 0;

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
      {count > 0 && (
        <NavLink
          to={`/lines/${lineId}/unclassified`}
          data-testid="unclassified-badge"
          aria-label={t("nav.unclassifiedLabel", { count })}
          className="ml-auto inline-flex items-center gap-2 rounded-full bg-amber-500 px-4 py-3 text-xl font-bold text-gray-900"
        >
          <CircleAlert aria-hidden className="h-6 w-6" />
          {t("nav.unclassified", { count })}
        </NavLink>
      )}
    </nav>
  );
}
