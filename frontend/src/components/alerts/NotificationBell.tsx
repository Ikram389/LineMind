import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";

import { getUnreadCount, listNotifications, markAllNotificationsRead, markNotificationRead } from "../../api/alerts.ts";
import { queryKeys } from "../../api/queryKeys.ts";
import { t } from "../../i18n/t.ts";
import { alertMessage, SEVERITY_STYLE } from "../../lib/alertText.ts";
import { formatTime } from "../../lib/time.ts";
import { buttonClass } from "../ui/buttonClass.ts";

const REFRESH_MS = 60_000; // a safety net: the user socket keeps the count live

/** The bell: unread count (live) and the latest notifications. */
export function NotificationBell() {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const unread = useQuery({ queryKey: queryKeys.unreadCount, queryFn: getUnreadCount, refetchInterval: REFRESH_MS });
  const latest = useQuery({
    queryKey: [...queryKeys.notifications, "latest"],
    queryFn: () => listNotifications(8),
    enabled: open,
  });
  const refresh = (count: number) => {
    queryClient.setQueryData(queryKeys.unreadCount, count);
    void queryClient.invalidateQueries({ queryKey: [...queryKeys.notifications, "latest"] });
  };
  const readAll = useMutation({ mutationFn: markAllNotificationsRead, onSuccess: (r) => refresh(r.unread_count) });
  const readOne = useMutation({ mutationFn: markNotificationRead, onSuccess: (r) => refresh(r.unread_count) });
  const count = unread.data ?? 0;

  return (
    <div className="relative">
      <button
        type="button"
        aria-label={t("bell.label", { count })}
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="relative inline-flex min-h-11 min-w-11 items-center justify-center rounded-control text-ink hover:bg-surface-muted"
      >
        <Bell aria-hidden className="h-6 w-6" />
        {count > 0 && (
          <span
            data-testid="bell-count"
            className="absolute right-0 top-0 min-w-5 rounded-full bg-critical px-1 text-center text-caption font-bold text-surface"
          >
            {count}
          </span>
        )}
      </button>
      {open && (
        <div
          role="dialog"
          aria-label={t("bell.title")}
          className="absolute right-0 z-50 mt-2 w-[min(28rem,calc(100vw-2rem))] rounded-card border border-line bg-surface p-3 text-ink shadow-lg"
        >
          {latest.data && latest.data.results.length === 0 && <p className="p-2 text-body text-ink-muted">{t("bell.empty")}</p>}
          <ul className="flex flex-col gap-2">
            {(latest.data?.results ?? []).map((n) => (
              <li key={n.id}>
                <Link
                  to={n.link}
                  onClick={() => {
                    if (!n.read_at) readOne.mutate(n.id);
                    setOpen(false);
                  }}
                  className={`block rounded-control border-l-4 p-2 ${SEVERITY_STYLE[n.severity]} ${n.read_at ? "opacity-70" : "font-semibold"}`}
                >
                  <span className="block text-body">{alertMessage(n.message_key, n.message_values)}</span>
                  <span className="text-small text-ink-muted">
                    {n.alert?.line?.name ?? String(n.message_values.line ?? "")} ·{" "}
                    {formatTime(n.created_at, n.alert?.factory_timezone ?? Intl.DateTimeFormat().resolvedOptions().timeZone)}
                    {n.reason === "escalated" && ` · ${t("bell.escalated")}`}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
          <div className="mt-3 flex justify-between gap-2">
            <button
              type="button"
              onClick={() => readAll.mutate()}
              disabled={count === 0}
              className={buttonClass("secondary")}
            >
              {t("bell.markAll")}
            </button>
            <Link to="/alerts" onClick={() => setOpen(false)} className={buttonClass("primary")}>
              {t("bell.all")}
            </Link>
          </div>
        </div>
      )}
    </div>
  );
}
