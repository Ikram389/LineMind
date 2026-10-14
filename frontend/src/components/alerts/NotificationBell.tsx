import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";

import { getUnreadCount, listNotifications, markAllNotificationsRead, markNotificationRead } from "../../api/alerts.ts";
import { queryKeys } from "../../api/queryKeys.ts";
import { t } from "../../i18n/t.ts";
import { alertMessage, SEVERITY_STYLE } from "../../lib/alertText.ts";
import { formatTime } from "../../lib/time.ts";

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
        className="relative rounded-lg p-2 hover:bg-gray-800"
      >
        <Bell aria-hidden className="h-8 w-8" />
        {count > 0 && (
          <span
            data-testid="bell-count"
            className="absolute -right-1 -top-1 min-w-7 rounded-full bg-red-600 px-2 text-center text-base font-bold"
          >
            {count}
          </span>
        )}
      </button>
      {open && (
        <div
          role="dialog"
          aria-label={t("bell.title")}
          className="absolute right-0 z-50 mt-2 w-[min(28rem,calc(100vw-2rem))] rounded-xl bg-white p-3 text-gray-900 shadow-2xl"
        >
          {latest.data && latest.data.results.length === 0 && <p className="p-2 text-lg">{t("bell.empty")}</p>}
          <ul className="flex flex-col gap-2">
            {(latest.data?.results ?? []).map((n) => (
              <li key={n.id}>
                <Link
                  to={`/alerts?alert=${n.alert.id}`}
                  onClick={() => {
                    if (!n.read_at) readOne.mutate(n.id);
                    setOpen(false);
                  }}
                  className={`block rounded-lg border-l-4 p-2 ${SEVERITY_STYLE[n.alert.severity]} ${n.read_at ? "opacity-70" : "font-semibold"}`}
                >
                  <span className="block text-lg">{alertMessage(n.alert.message_key, n.alert.message_values)}</span>
                  <span className="text-base">
                    {n.alert.line?.name ?? ""} · {formatTime(n.created_at, n.alert.factory_timezone)}
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
              className="min-h-11 rounded-lg border border-gray-400 px-3 text-lg disabled:opacity-40"
            >
              {t("bell.markAll")}
            </button>
            <Link to="/alerts" onClick={() => setOpen(false)} className="min-h-11 rounded-lg bg-gray-900 px-3 py-2 text-lg text-white">
              {t("bell.all")}
            </Link>
          </div>
        </div>
      )}
    </div>
  );
}
