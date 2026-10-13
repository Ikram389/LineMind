import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { queryKeys } from "../api/queryKeys.ts";
import type { LineStatus } from "../api/types.ts";
import { LiveIndicator } from "../components/LiveIndicator.tsx";
import { NOW_MS, makeMachine, makeStatus } from "../test/fixtures.ts";
import { setSocketFactory, useLineLive } from "./useLineLive.ts";

vi.mock("../api/endpoints.ts", () => ({
  getWsTicket: vi.fn(() => Promise.resolve({ ticket: "t-1", expires_in: 30 })),
}));

/** A controllable stand-in for the browser WebSocket. */
class FakeSocket {
  static instances: FakeSocket[] = [];
  url: string;
  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  onclose: (() => void) | null = null;

  constructor(url: string) {
    this.url = url;
    FakeSocket.instances.push(this);
  }
  open() {
    this.onopen?.();
  }
  send(message: unknown) {
    this.onmessage?.({ data: JSON.stringify(message) } as MessageEvent<string>);
  }
  serverClose() {
    this.onclose?.();
  }
  close() {}
}

function Harness({ lineId }: { lineId: number }) {
  return <LiveIndicator status={useLineLive(lineId)} />;
}

function setup() {
  const queryClient = new QueryClient();
  queryClient.setQueryData(queryKeys.lineStatus(1), makeStatus([makeMachine()]));
  render(
    <QueryClientProvider client={queryClient}>
      <Harness lineId={1} />
    </QueryClientProvider>,
  );
  return queryClient;
}

async function flush() {
  await act(async () => {
    await Promise.resolve();
  });
}

beforeEach(() => {
  FakeSocket.instances = [];
  setSocketFactory((url) => new FakeSocket(url) as unknown as WebSocket);
});

describe("useLineLive", () => {
  it("connects with a ticket and shows Live", async () => {
    setup();
    await flush();
    const socket = FakeSocket.instances[0];
    expect(socket?.url).toMatch(/\/ws\/lines\/1\/\?ticket=t-1$/);

    act(() => socket?.open());

    expect(screen.getByText("Live")).toBeInTheDocument();
  });

  it("updates the cached machine from a state message", async () => {
    const queryClient = setup();
    await flush();
    const socket = FakeSocket.instances[0];
    act(() => socket?.open());

    act(() =>
      socket?.send({
        type: "machine_state_changed",
        line_id: 1,
        sent_at: new Date(NOW_MS).toISOString(),
        data: {
          machine_id: 5,
          external_id: "M05",
          state: "stopped",
          reported_state: "stopped",
          state_since: new Date(NOW_MS).toISOString(),
          alarm_code: "E-204",
          last_alarm_code: "E-204",
          last_alarm_at: new Date(NOW_MS).toISOString(),
          is_stale: false,
          last_seen: new Date(NOW_MS).toISOString(),
        },
      }),
    );

    const machine = queryClient.getQueryData<LineStatus>(queryKeys.lineStatus(1))?.machines[0];
    expect(machine?.state).toBe("stopped");
    expect(machine?.alarm_code).toBe("E-204");
  });

  it("shows the reconnecting indicator when the socket closes, then reconnects and re-fetches", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: false });
    const queryClient = setup();
    await flush();
    act(() => FakeSocket.instances[0]?.open());
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");

    act(() => FakeSocket.instances[0]?.serverClose());

    expect(screen.getByRole("status")).toHaveTextContent("Live updates paused, reconnecting…");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000); // first backoff
    });
    expect(FakeSocket.instances).toHaveLength(2);

    act(() => FakeSocket.instances[1]?.open());

    expect(screen.getByText("Live")).toBeInTheDocument();
    expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.lineStatus(1) });
  });

  it("clears the incident when it closes", async () => {
    const queryClient = setup();
    queryClient.setQueryData<LineStatus>(queryKeys.lineStatus(1), (old) =>
      old
        ? {
            ...old,
            open_incident: {
              incident_id: 7,
              started_at: new Date(NOW_MS).toISOString(),
              ended_at: null,
              origin: "machine_stop",
              first_observed_stop: { machines: [], alarm_code: null },
              affected_machines: [],
            },
          }
        : old,
    );
    await flush();
    const socket = FakeSocket.instances[0];
    act(() => socket?.open());

    act(() =>
      socket?.send({
        type: "incident_closed",
        line_id: 1,
        sent_at: new Date(NOW_MS).toISOString(),
        data: { incident_id: 7, started_at: "", ended_at: "", duration_seconds: 91 },
      }),
    );

    expect(queryClient.getQueryData<LineStatus>(queryKeys.lineStatus(1))?.open_incident).toBeNull();
  });
});
