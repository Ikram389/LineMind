import {
  BadgeCheck,
  ChevronsLeft,
  ChevronsRight,
  LayoutDashboard,
  ListChecks,
  type LucideIcon,
  Settings,
  SlidersHorizontal,
  Siren,
  Tags,
  TimerOff,
  Wrench,
} from "lucide-react";
import type { ReactNode } from "react";
import { NavLink } from "react-router";

import { t } from "../../i18n/t.ts";
import { cn } from "../../lib/cn.ts";
import { usePermissions } from "../../lib/permissions.ts";
import { Tooltip } from "../ui/Toast.tsx";

interface ItemProps {
  to: string;
  label: string;
  Icon: LucideIcon;
  collapsed: boolean;
  end?: boolean;
  /** A count shown as a pill (e.g. open alerts); the accessible name says it in words. */
  count?: number;
  accessibleName?: string;
}

function Item({ to, label, Icon, collapsed, end, count, accessibleName }: ItemProps) {
  const link = (
    <NavLink
      to={to}
      end={end}
      aria-label={accessibleName}
      className={({ isActive }) =>
        cn(
          "relative flex min-h-11 items-center gap-3 rounded-control px-3 text-body font-semibold",
          isActive ? "bg-accent-soft text-accent" : "text-ink-muted hover:bg-surface-muted hover:text-ink",
          collapsed && "justify-center px-0",
        )
      }
    >
      <Icon aria-hidden className="h-5 w-5 shrink-0" />
      <span className={collapsed ? "sr-only" : "flex-1 truncate"}>{label}</span>
      {count !== undefined && count > 0 && (
        <span
          aria-hidden
          className={cn(
            "rounded-full bg-critical px-1.5 text-caption font-bold text-surface",
            collapsed && "absolute right-1 top-1",
          )}
        >
          {count}
        </span>
      )}
    </NavLink>
  );
  return <li>{collapsed ? <Tooltip label={accessibleName ?? label} side="right">{link}</Tooltip> : link}</li>;
}

function Group({ label, collapsed, children }: { label?: string; collapsed: boolean; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      {label && (
        <p className={cn("px-3 pb-1 pt-4 text-caption font-semibold uppercase tracking-wide text-ink-muted", collapsed && "sr-only")}>
          {label}
        </p>
      )}
      <ul className="flex flex-col gap-1">{children}</ul>
    </div>
  );
}

interface SidebarProps {
  lineId: number | null;
  collapsed: boolean;
  onToggle: () => void;
  openAlerts: number;
}

/** The slim left menu. Line pages go to the current line; managers also see "Manage". */
export function Sidebar({ lineId, collapsed, onToggle, openAlerts }: SidebarProps) {
  const { canManageReasons, canManageQuality, canManageAlertRules } = usePermissions();
  const line = lineId === null ? null : `/lines/${lineId}`;
  const manage = line !== null && (canManageReasons || canManageQuality);

  return (
    // The outer column fills the page height (background and border); the menu inside stays in view.
    <div className={cn("shrink-0 border-r border-line bg-chrome", collapsed ? "w-[4.5rem]" : "w-60")}>
    <nav aria-label={t("shell.nav")} className="sticky top-0 flex h-screen flex-col p-3">
      <p className={cn("flex h-11 items-center px-3 text-title font-extrabold text-ink", collapsed && "justify-center px-0")}>
        <span aria-hidden className="grid h-8 w-8 shrink-0 place-items-center rounded-control bg-accent text-small text-on-accent">
          LM
        </span>
        <span className={collapsed ? "sr-only" : "ml-2"}>{t("appbar.home")}</span>
      </p>

      <div className="mt-4 flex flex-1 flex-col justify-between gap-4 overflow-y-auto">
        <div>
          <Group collapsed={collapsed}>
            <Item to={line ?? "/"} end label={t("nav.overview")} Icon={LayoutDashboard} collapsed={collapsed} />
            {line && <Item to={`${line}/downtime`} label={t("nav.downtime")} Icon={TimerOff} collapsed={collapsed} />}
            {line && <Item to={`${line}/quality`} label={t("nav.quality")} Icon={BadgeCheck} collapsed={collapsed} />}
            <Item to="/maintenance" label={t("appbar.maintenance")} Icon={Wrench} collapsed={collapsed} />
            <Item
              to="/alerts"
              label={t("appbar.alerts")}
              Icon={Siren}
              collapsed={collapsed}
              count={openAlerts}
              accessibleName={openAlerts > 0 ? t("appbar.openAlerts", { count: openAlerts }) : undefined}
            />
          </Group>
        </div>

        <div>
          {(manage || canManageAlertRules) && (
            <Group label={t("shell.manage")} collapsed={collapsed}>
              {line && canManageReasons && (
                <Item to={`${line}/reasons`} label={t("nav.reasons")} Icon={Tags} collapsed={collapsed} />
              )}
              {line && canManageQuality && (
                <Item to={`${line}/quality-setup`} label={t("nav.qualitySetup")} Icon={SlidersHorizontal} collapsed={collapsed} />
              )}
              {canManageAlertRules && (
                <Item to="/alert-rules" label={t("appbar.rules")} Icon={ListChecks} collapsed={collapsed} />
              )}
            </Group>
          )}
          <Group collapsed={collapsed}>
            <Item to="/settings" label={t("appbar.settings")} Icon={Settings} collapsed={collapsed} />
          </Group>
          <button
            type="button"
            onClick={onToggle}
            aria-label={collapsed ? t("shell.expand") : t("shell.collapse")}
            aria-expanded={!collapsed}
            className={cn(
              "mt-2 flex min-h-11 w-full items-center gap-3 rounded-control px-3 text-body text-ink-muted hover:bg-surface-muted",
              collapsed && "justify-center px-0",
            )}
          >
            {collapsed ? <ChevronsRight aria-hidden className="h-5 w-5" /> : <ChevronsLeft aria-hidden className="h-5 w-5" />}
            <span className={collapsed ? "sr-only" : ""}>{t("shell.collapse")}</span>
          </button>
        </div>
      </div>
    </nav>
    </div>
  );
}
