/**
 * Live updates for one line.
 *
 * 1. Ask the backend for a single-use ticket (with the user's JWT).
 * 2. Open ws(s)://<host>/ws/lines/<id>/?ticket=...
 * 3. Merge each message into the cached /status/ data (TanStack Query), and
 *    refresh the OEE when an incident opens or closes.
 * 4. On disconnect: report "reconnecting" (the page then polls every 15 s), retry
 *    with backoff (1, 2, 4 ... 30 s) and re-fetch everything once reconnected.
 */
import { type QueryClient, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { getWsTicket } from "../api/endpoints.ts";
import { queryKeys } from "../api/queryKeys.ts";
import type { LineStatus, LiveMessage, MachineStatus } from "../api/types.ts";
import { recordServerTime } from "../lib/serverClock.ts";

export type LiveStatus = "connecting" | "live" | "reconnecting";

/** Opens a WebSocket. Replaced in tests. */
export type SocketFactory = (url: string) => WebSocket;
let socketFactory: SocketFactory = (url) => new WebSocket(url);
export function setSocketFactory(factory: SocketFactory): void {
  socketFactory = factory;
}

const MAX_BACKOFF_MS = 30_000;

export function backoffMs(attempt: number): number {
  return Math.min(MAX_BACKOFF_MS, 1000 * 2 ** attempt);
}

function socketUrl(lineId: number, ticket: string): string {
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  return `${protocol}://${window.location.host}/ws/lines/${lineId}/?ticket=${encodeURIComponent(ticket)}`;
}

function updateMachine(
  status: LineStatus,
  machineId: number,
  patch: Partial<MachineStatus>,
): LineStatus {
  return {
    ...status,
    machines: status.machines.map((m) => (m.id === machineId ? { ...m, ...patch } : m)),
  };
}

/** Apply one live message to the cache. Exported for tests. */
export function applyLiveMessage(
  queryClient: QueryClient,
  lineId: number,
  message: LiveMessage,
): void {
  recordServerTime(Date.parse(message.sent_at));
  const key = queryKeys.lineStatus(lineId);
  const current = queryClient.getQueryData<LineStatus>(key);

  switch (message.type) {
    case "machine_state_changed": {
      const d = message.data;
      if (current) {
        queryClient.setQueryData(
          key,
          updateMachine(current, d.machine_id, {
            state: d.state,
            reported_state: d.reported_state,
            state_since: d.state_since,
            alarm_code: d.alarm_code,
            last_alarm_code: d.last_alarm_code,
            last_alarm_at: d.last_alarm_at,
            is_stale: d.is_stale,
            last_seen: d.last_seen,
          }),
        );
      }
      return;
    }
    case "count_updated": {
      const d = message.data;
      if (current) {
        queryClient.setQueryData(
          key,
          updateMachine(current, d.machine_id, {
            shift_count: d.shift_count,
            shift_rejected: d.shift_rejected,
            last_seen: d.last_seen,
            last_count:
              d.count !== null && d.timestamp !== null
                ? { count: d.count, rejected: d.rejected, timestamp: d.timestamp }
                : null,
          }),
        );
      }
      return;
    }
    case "incident_opened":
    case "incident_updated":
      if (current) queryClient.setQueryData(key, { ...current, open_incident: message.data });
      if (message.type === "incident_opened") {
        void queryClient.invalidateQueries({ queryKey: queryKeys.oee(lineId) });
      }
      void queryClient.invalidateQueries({ queryKey: queryKeys.downtime });
      return;
    case "incident_closed":
      if (current && current.open_incident?.incident_id === message.data.incident_id) {
        queryClient.setQueryData(key, { ...current, open_incident: null });
      }
      void queryClient.invalidateQueries({ queryKey: queryKeys.oee(lineId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.downtime });
      return;
    default:
      // Unknown message: fall back to the full state from the REST API.
      void queryClient.invalidateQueries({ queryKey: key });
  }
}

export function useLineLive(
  lineId: number | null,
  onMessage?: (message: LiveMessage) => void,
): LiveStatus {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<LiveStatus>("connecting");
  // Keep the latest callback without reconnecting when it changes.
  const onMessageRef = useRef(onMessage);
  useEffect(() => {
    onMessageRef.current = onMessage;
  }, [onMessage]);

  useEffect(() => {
    if (lineId === null) return;
    let socket: WebSocket | null = null;
    let timer: number | undefined;
    let attempt = 0;
    let everConnected = false;
    let stopped = false;

    const scheduleReconnect = () => {
      if (stopped) return;
      setStatus("reconnecting");
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
      const ws = socketFactory(socketUrl(lineId as number, ticket));
      socket = ws;
      ws.onopen = () => {
        const reconnected = everConnected || attempt > 0;
        everConnected = true;
        attempt = 0;
        setStatus("live");
        if (reconnected) {
          // We may have missed messages: re-fetch the full state.
          void queryClient.invalidateQueries({ queryKey: queryKeys.lineStatus(lineId as number) });
          void queryClient.invalidateQueries({ queryKey: queryKeys.oee(lineId as number) });
          void queryClient.invalidateQueries({ queryKey: ["currentShift"] });
        }
      };
      ws.onmessage = (event: MessageEvent<string>) => {
        try {
          const message = JSON.parse(event.data) as LiveMessage;
          applyLiveMessage(queryClient, lineId as number, message);
          onMessageRef.current?.(message);
        } catch {
          void queryClient.invalidateQueries({ queryKey: queryKeys.lineStatus(lineId as number) });
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
  }, [lineId, queryClient]);

  return status;
}
