/** The line selector and the account menu in the top bar. */
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, LogOut, Settings } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { Link, useNavigate } from "react-router";

import { listLines } from "../../api/endpoints.ts";
import { queryKeys } from "../../api/queryKeys.ts";
import { useAuth } from "../../auth/context.ts";
import { t } from "../../i18n/t.ts";
import { cn } from "../../lib/cn.ts";
import { type Theme, useTheme } from "../../lib/theme.ts";
import { SegmentedControl } from "../ui/Choice.tsx";
import { controlClass } from "../ui/Field.tsx";

/** Switches line and keeps the page (Downtime on line 1 → Downtime on line 2). */
export function LineSelector({ lineId, subPage }: { lineId: number | null; subPage: string }) {
  const id = useId();
  const navigate = useNavigate();
  const lines = useQuery({ queryKey: queryKeys.lines, queryFn: listLines });
  const list = lines.data ?? [];
    const current = list.find((line) => line.id === lineId);
  if (list.length <= 1) return null; // nothing to choose (the page header names the line)
  return (
    <div className="flex items-center gap-2">
      <label htmlFor={id} className="sr-only">
        {t("shell.line")}
      </label>
      <select
        id={id}
        value={current?.id ?? ""}
        onChange={(event) => navigate(`/lines/${event.target.value}${subPage}`)}
        className={cn(controlClass, "min-w-48 font-semibold")}
      >
        {!current && (
          <option value="" disabled>
            {t("shell.chooseLine")}
          </option>
        )}
        {list.map((line) => (
          <option key={line.id} value={line.id}>
            {line.name}
          </option>
        ))}
      </select>
    </div>
  );
}

/** The user's initials in a circle; opens theme, Settings and Log out. */
export function UserMenu() {
  const { user, logout } = useAuth();
  const [theme, setTheme] = useTheme();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDown = (event: MouseEvent) => {
      if (!ref.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);
  const email = user?.email ?? "";
  const initials = (user?.full_name || email).slice(0, 2).toUpperCase();

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        aria-expanded={open}
        aria-label={t("shell.userMenu", { email })}
        onClick={() => setOpen((v) => !v)}
        className="flex min-h-11 items-center gap-2 rounded-control px-2 text-ink hover:bg-surface-muted"
      >
        <span aria-hidden className="grid h-8 w-8 place-items-center rounded-full bg-accent-soft text-small font-bold text-accent">
          {initials}
        </span>
        <ChevronDown aria-hidden className="h-4 w-4 text-ink-muted" />
      </button>
      {open && (
        <div className="absolute right-0 z-50 mt-2 flex w-72 flex-col gap-3 rounded-card border border-line bg-surface p-4 shadow-lg">
          <p className="truncate text-small text-ink-muted">{email}</p>
          <SegmentedControl<Theme>
            label={t("theme.label")}
            value={theme}
            onChange={setTheme}
            options={[
              { value: "light", label: t("theme.light") },
              { value: "dark", label: t("theme.dark") },
            ]}
          />
          <Link
            to="/settings"
            onClick={() => setOpen(false)}
            className="flex min-h-11 items-center gap-2 rounded-control px-2 text-body font-semibold text-ink hover:bg-surface-muted"
          >
            <Settings aria-hidden className="h-5 w-5" />
            {t("appbar.settings")}
          </Link>
          <button
            type="button"
            onClick={logout}
            className="flex min-h-11 items-center gap-2 rounded-control px-2 text-body font-semibold text-ink hover:bg-surface-muted"
          >
            <LogOut aria-hidden className="h-5 w-5" />
            {t("nav.logout")}
          </button>
        </div>
      )}
    </div>
  );
}
