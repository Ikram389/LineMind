import { useQuery } from "@tanstack/react-query";
import { TriangleAlert, Wrench } from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";
import { Link, Outlet, useSearchParams } from "react-router";

import { getHealth, listAlerts } from "../api/alerts.ts";
import { getMyOpenCount } from "../api/maintenance.ts";
import { queryKeys } from "../api/queryKeys.ts";
import { t } from "../i18n/t.ts";
import { mediaMatches, useCurrentLine } from "../lib/currentLine.ts";
import { usePermissions } from "../lib/permissions.ts";
import { useAuth } from "../auth/context.ts";
import { applyTheme, readTheme, useTheme } from "../lib/theme.ts";
import { useUserLive } from "../live/useUserLive.ts";
import { NotificationBell } from "./alerts/NotificationBell.tsx";
import { Sidebar } from "./shell/Sidebar.tsx";
import { LineSelector, UserMenu } from "./shell/TopBarParts.tsx";

const HEALTH_REFRESH_MS = 60_000;
/** Below this width (tablets, small laptops) the sidebar starts collapsed. */
const NARROW = "(max-width: 1365px)";

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
    <p
      role="alert"
      data-testid="engine-stale"
      className="flex items-center gap-2 border-b border-critical bg-critical-soft px-6 py-2 text-body font-semibold text-critical"
    >
      <TriangleAlert aria-hidden className="h-5 w-5 shrink-0" />
      {last ? t("appbar.engineStale", { time: formatLocalTime(last) }) : t("appbar.engineNever")}
    </p>
  );
}

/** Starts collapsed on narrow screens; the user's toggle wins until the width class changes. */
function useSidebarCollapsed(): [boolean, () => void] {
  const [narrow, setNarrow] = useState(() => mediaMatches(NARROW));
  const [override, setOverride] = useState<boolean | null>(null);
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const query = window.matchMedia(NARROW);
    const onChange = () => {
      setNarrow(query.matches);
      setOverride(null);
    };
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);
  const collapsed = override ?? narrow;
  return [collapsed, () => setOverride(!collapsed)];
}

/** The frame of every signed-in page: the left menu, the top bar (line, my actions, bell,
 * account) and the alert engine warning, around the page itself. */
export function AppBar({ children }: { children?: ReactNode }) {
  const { canResolveAlerts } = usePermissions();
  const { lineId, subPage } = useCurrentLine();
  const [collapsed, toggle] = useSidebarCollapsed();
  useUserLive(true);
  const open = useQuery({
    queryKey: queryKeys.alertList({ status: "unresolved", limit: 1 }),
    queryFn: () => listAlerts({ status: "unresolved", limit: 1 }),
    refetchInterval: HEALTH_REFRESH_MS,
  });
  const mine = useQuery({ queryKey: queryKeys.myOpenActions, queryFn: getMyOpenCount, refetchInterval: HEALTH_REFRESH_MS });
  const myCount = mine.data ?? 0;

  return (
    <div className="flex min-h-screen bg-canvas text-ink">
      <a
        href="#content"
        className="sr-only z-50 rounded-control bg-accent px-4 py-2 text-on-accent focus:not-sr-only focus:fixed focus:left-4 focus:top-4"
      >
        {t("shell.skip")}
      </a>
      <Sidebar lineId={lineId} collapsed={collapsed} onToggle={toggle} openAlerts={open.data?.count ?? 0} />
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-16 items-center gap-3 border-b border-line bg-chrome px-4 sm:px-6">
          <LineSelector lineId={lineId} subPage={subPage} />
          <div className="ml-auto flex items-center gap-1">
            {myCount > 0 && (
              <Link
                to="/maintenance?mine=true"
                aria-label={t("appbar.myActions", { count: myCount })}
                data-testid="my-actions-badge"
                className="inline-flex min-h-11 items-center gap-1 rounded-full bg-warning-soft px-3 text-body font-bold text-warning hover:bg-surface-muted"
              >
                <Wrench aria-hidden className="h-5 w-5" />
                {myCount}
              </Link>
            )}
            <NotificationBell />
            <UserMenu />
          </div>
        </header>
        {canResolveAlerts && <AlertEngineWarning />}
        <div id="content" className="flex min-w-0 flex-1 flex-col">
          {children}
        </div>
      </div>
    </div>
  );
}

/** TV mode (?tv=1): no menus, dark, everything larger. Leaving it restores the user's theme. */
function useTvMode(tv: boolean, userId: number | undefined) {
  useEffect(() => {
    if (!tv) return;
    const root = document.documentElement;
    root.classList.add("tv");
    applyTheme("dark");
    return () => {
      root.classList.remove("tv");
      applyTheme(readTheme(userId));
    };
  }, [tv, userId]);
}

/** Layout route: the frame around every signed-in page, or nothing at all in TV mode. */
export function AppLayout() {
  useTheme(); // applies the user's theme
  const userId = useAuth().user?.id;
  const tv = useSearchParams()[0].get("tv") === "1";
  useTvMode(tv, userId);
  if (tv) {
    return (
      <div data-testid="tv-mode" className="min-h-screen bg-canvas text-ink">
        <Outlet />
      </div>
    );
  }
  return (
    <AppBar>
      <Outlet />
    </AppBar>
  );
}
