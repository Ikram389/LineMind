import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router";

import { getLineStatus, getOee } from "../api/endpoints.ts";
import { queryKeys } from "../api/queryKeys.ts";
import { Header } from "../components/Header.tsx";
import { IncidentBanner } from "../components/IncidentBanner.tsx";
import { LiveIndicator } from "../components/LiveIndicator.tsx";
import { MachineFlow } from "../components/MachineFlow.tsx";
import { OeeHourlyChart } from "../components/OeeHourlyChart.tsx";
import { OeePanel } from "../components/OeePanel.tsx";
import { Panel } from "../components/Panel.tsx";
import { t } from "../i18n/t.ts";
import { serverNow, useServerNow } from "../lib/serverClock.ts";
import { useLineLive } from "../live/useLineLive.ts";
import { useLineContext } from "./useLineContext.ts";

const POLL_WHEN_DISCONNECTED_MS = 15_000;
const OEE_REFRESH_MS = 60_000;

export function LineOverviewPage() {
  const lineId = Number(useParams().lineId);
  const nowMs = useServerNow();
  const live = useLineLive(lineId);
  const { line, factory, shift } = useLineContext(lineId);

  const status = useQuery({
    queryKey: queryKeys.lineStatus(lineId),
    queryFn: () => getLineStatus(lineId),
    // Live messages keep this up to date; while disconnected, poll instead.
    refetchInterval: live === "live" ? false : POLL_WHEN_DISCONNECTED_MS,
  });

  const currentShift = shift.data ?? null;
  const shiftStart = currentShift?.start ?? null;
  const oee = useQuery({
    queryKey: [...queryKeys.oee(lineId), shiftStart],
    queryFn: async () => {
      if (!currentShift) throw new Error("No shift running.");
      // From the shift start until now: never into the future.
      const end = new Date(Math.min(serverNow(), Date.parse(currentShift.end))).toISOString();
      const [total, hourly] = await Promise.all([
        getOee(lineId, currentShift.start, end),
        getOee(lineId, currentShift.start, end, "hour"),
      ]);
      return { total: total.total, buckets: hourly.buckets ?? [] };
    },
    enabled: currentShift !== null,
    refetchInterval: OEE_REFRESH_MS,
  });

  const zone = status.data?.factory_timezone ?? factory.data?.timezone ?? "UTC";
  const incident = status.data?.open_incident ?? null;

  return (
    <main className="flex min-h-screen flex-col gap-4 bg-gray-100 p-4">
      <Header
        factoryName={factory.data?.name ?? ""}
        lineName={line.data?.name ?? ""}
        zone={zone}
        shift={shift.data}
        nowMs={nowMs}
        live={<LiveIndicator status={live} />}
      />

      {incident && <IncidentBanner incident={incident} nowMs={nowMs} />}

      <Panel isLoading={status.isLoading} isError={status.isError && !status.data}>
        {status.data && (
          <MachineFlow
            machines={status.data.machines}
            incident={incident}
            staleAfterSeconds={status.data.stale_after_seconds}
            nowMs={nowMs}
            shiftStart={shiftStart}
            machineHref={(machine) => `/lines/${lineId}/machines/${machine.id}`}
          />
        )}
      </Panel>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel
          title={t("oee.title")}
          isLoading={shiftStart !== null && oee.isLoading}
          isError={oee.isError && !oee.data}
          isEmpty={!shift.isLoading && shift.data === null}
          emptyText={t("oee.noShift")}
        >
          {oee.data && <OeePanel result={oee.data.total} />}
        </Panel>
        <Panel
          title={t("oee.hourly")}
          isLoading={shiftStart !== null && oee.isLoading}
          isError={oee.isError && !oee.data}
          isEmpty={shift.data === null || oee.data?.buckets.length === 0}
          emptyText={shift.data === null ? t("oee.noShift") : t("oee.hourlyEmpty")}
        >
          {oee.data && <OeeHourlyChart buckets={oee.data.buckets} zone={zone} />}
        </Panel>
      </div>
    </main>
  );
}
