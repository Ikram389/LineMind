import { useQuery } from "@tanstack/react-query";
import { TriangleAlert } from "lucide-react";
import { Link, NavLink, Outlet } from "react-router";

import { getHealth, listAlerts } from "../api/alerts.ts";
import { queryKeys } from "../api/queryKeys.ts";
import { useAuth } from "../auth/context.ts";
import { t } from "../i18n/t.ts";
import { usePermissions } from "../lib/permissions.ts";
import { useUserLive } from "../live/useUserLive.ts";
import { NotificationBell } from "./alerts/NotificationBell.tsx";

const HEALTH_REFRESH_MS = 60_000;

const link = ({ isActive }: { isActive: boolean }) =>
  `rounded-lg px-3 py-2 text-lg font-semibold ${isActive ? "bg-white text-gray-900" : "hover:bg-gray-800"}`;

function formatLocalTime(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
}

/** Supervisors and above see when the alert engine stopped checking (it would look like
 * "no problems" otherwise). */
export function AlertEngineWarning() {
  const health = useQuery({ queryKey: queryKeys.health, queryFn: getHealth, refetchInterval: HEALTH_REFRESH_MS });
  if (health.data?.alerts !== "stale") return null;
  const last = health.data.alerts_last_heartbeat;
  return (
    <p role="alert" data-testid="engine-stale" className="flex items-center gap-2 bg-red-700 px-4 py-2 text-lg font-semibold text-white">
      <TriangleAlert aria-hidden className="h-6 w-6 shrink-0" />
      {last ? t("appbar.engineStale", { time: formatLocalTime(last) }) : t("appbar.engineNever")}
    </p>
  );
}

/** The bar on every signed-in page: navigation, open alerts, the bell, settings, log out. */
export function AppBar() {
  const { logout } = useAuth();
  const { canResolveAlerts, canManageAlertRules } = usePermissions();
  useUserLive(true);
  const open = useQuery({
    queryKey: queryKeys.alertList({ status: "unresolved", limit: 1 }),
    queryFn: () => listAlerts({ status: "unresolved", limit: 1 }),
    refetchInterval: HEALTH_REFRESH_MS,
  });
  const openCount = open.data?.count ?? 0;

  return (
    <>
      <nav aria-label="Main" className="flex flex-wrap items-center gap-2 bg-gray-900 px-4 py-2 text-white">
        <Link to="/" className="mr-2 text-2xl font-extrabold">
          {t("appbar.home")}
        </Link>
        <NavLink to="/" end className={link}>
          {t("appbar.lines")}
        </NavLink>
        <NavLink to="/alerts" className={link}>
          {openCount > 0 ? t("appbar.openAlerts", { count: openCount }) : t("appbar.alerts")}
        </NavLink>
        {canManageAlertRules && (
          <NavLink to="/alert-rules" className={link}>
            {t("appbar.rules")}
          </NavLink>
        )}
        <div className="ml-auto flex items-center gap-2">
          <NotificationBell />
          <NavLink to="/settings" className={link}>
            {t("appbar.settings")}
          </NavLink>
          <button type="button" onClick={logout} className="rounded-md border border-gray-500 px-3 py-2 text-lg hover:bg-gray-800">
            {t("nav.logout")}
          </button>
        </div>
      </nav>
      {canResolveAlerts && <AlertEngineWarning />}
    </>
  );
}

/** Layout route: the bar above every signed-in page. */
export function AppLayout() {
  return (
    <>
      <AppBar />
      <Outlet />
    </>
  );
}
