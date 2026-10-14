/**
 * The signed-in user's own live channel (/ws/me/): their unread notification count.
 * Same ticket and reconnect rules as the line socket (useLineLive.ts).
 */
import { type QueryClient, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import { getWsTicket } from "../api/endpoints.ts";
import { queryKeys } from "../api/queryKeys.ts";
import type { NotificationsChanged } from "../api/types.ts";
import { backoffMs, openSocket } from "./useLineLive.ts";

/** Apply one message from the user socket. Exported for tests. */
export function applyUserMessage(queryClient: QueryClient, message: NotificationsChanged): void {
  if (message.type !== "notifications_changed") return;
  queryClient.setQueryData(queryKeys.unreadCount, message.data.unread_count);
  void queryClient.invalidateQueries({
    queryKey: queryKeys.notifications,
    predicate: (query) => query.queryKey[1] !== "unread",
  });
  void queryClient.invalidateQueries({ queryKey: queryKeys.alerts });
  void queryClient.invalidateQueries({ queryKey: queryKeys.myOpenActions });
}

export function useUserLive(enabled: boolean): void {
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!enabled) return;
    let socket: WebSocket | null = null;
    let timer: number | undefined;
    let attempt = 0;
    let stopped = false;

    const scheduleReconnect = () => {
      if (stopped) return;
      timer = window.setTimeout(connect, backoffMs(attempt));
      attempt += 1;
    };

    async function connect(): Promise<void> {
      let ticket: string;
      try {
        ticket = (await getWsTicket()).ticket;
      } catch {
        scheduleReconnect();
        return;
      }
      if (stopped) return;
      const protocol = window.location.protocol === "https:" ? "wss" : "ws";
      const ws = openSocket(`${protocol}://${window.location.host}/ws/me/?ticket=${encodeURIComponent(ticket)}`);
      socket = ws;
      ws.onopen = () => {
        if (attempt > 0) void queryClient.invalidateQueries({ queryKey: queryKeys.notifications });
        attempt = 0;
      };
      ws.onmessage = (event: MessageEvent<string>) => {
        try {
          applyUserMessage(queryClient, JSON.parse(event.data) as NotificationsChanged);
        } catch {
          void queryClient.invalidateQueries({ queryKey: queryKeys.notifications });
        }
      };
      ws.onclose = () => {
        if (socket === ws) socket = null;
        scheduleReconnect();
      };
    }

    void connect();
    return () => {
      stopped = true;
      window.clearTimeout(timer);
      if (socket) {
        socket.onclose = null;
        socket.close();
      }
    };
  }, [enabled, queryClient]);
}
