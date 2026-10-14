import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router";

import { getLineStatus, listMachineDowntime } from "../api/endpoints.ts";
import { queryKeys } from "../api/queryKeys.ts";
import { DowntimeTable } from "../components/DowntimeTable.tsx";
import { MachineCard } from "../components/MachineCard.tsx";
import { MachineActions } from "../components/maintenance/MachineActions.tsx";
import { Panel } from "../components/Panel.tsx";
import { StateTimeline } from "../components/StateTimeline.tsx";
import { t } from "../i18n/t.ts";
import { serverNow, useServerNow } from "../lib/serverClock.ts";
import { buildTimeline } from "../lib/timeline.ts";
import { useLineContext } from "./useLineContext.ts";

export function MachineDetailPage() {
  const params = useParams();
  const lineId = Number(params.lineId);
  const machineId = Number(params.machineId);
  const nowMs = useServerNow();
  const { shift } = useLineContext(lineId);

  const status = useQuery({
    queryKey: queryKeys.lineStatus(lineId),
    queryFn: () => getLineStatus(lineId),
    refetchInterval: 15_000,
  });
  const shiftStart = shift.data?.start ?? null;
  const downtime = useQuery({
    queryKey: [...queryKeys.machineDowntime(machineId), shiftStart],
    queryFn: () => {
      if (!shiftStart) throw new Error("No shift running.");
      return listMachineDowntime(machineId, shiftStart, new Date(serverNow()).toISOString());
    },
    enabled: shiftStart !== null,
    refetchInterval: 15_000,
  });

  const machine = status.data?.machines.find((m) => m.id === machineId);
  const zone = status.data?.factory_timezone ?? "UTC";
  const fromMs = shiftStart ? Date.parse(shiftStart) : nowMs;
  const toMs = shift.data ? Math.min(nowMs, Date.parse(shift.data.end)) : nowMs;
  const knownUntil =
    machine?.last_seen && status.data
      ? Date.parse(machine.last_seen) + status.data.stale_after_seconds * 1000
      : null;

  return (
    <main className="mx-auto flex max-w-6xl flex-col gap-4 p-4">
      <Link to={`/lines/${lineId}`} className="text-xl text-blue-800 underline">
        {t("nav.backToLine")}
      </Link>

      <Panel isLoading={status.isLoading} isError={status.isError && !status.data}>
        {machine && status.data && (
          <div className="max-w-sm">
            <MachineCard
              machine={machine}
              staleAfterSeconds={status.data.stale_after_seconds}
              nowMs={nowMs}
              shiftStart={shiftStart}
              isFirstStop={
                status.data.open_incident?.first_observed_stop.machines.some(
                  (m) => m.id === machine.id,
                ) ?? false
              }
            />
          </div>
        )}
      </Panel>

      <Panel
        title={t("detail.timeline")}
        isLoading={downtime.isLoading}
        isError={downtime.isError && !downtime.data}
        isEmpty={shift.data === null}
        emptyText={t("shift.none")}
      >
        {downtime.data && (
          <>
            <StateTimeline
              segments={buildTimeline(downtime.data.results, fromMs, toMs, knownUntil)}
              fromMs={fromMs}
              toMs={toMs}
              zone={zone}
            />
            <p className="text-sm text-gray-500">{t("detail.timelineNote")}</p>
          </>
        )}
      </Panel>

      <Panel
        title={t("detail.downtime")}
        isLoading={downtime.isLoading}
        isError={downtime.isError && !downtime.data}
        isEmpty={shift.data === null || downtime.data?.results.length === 0}
        emptyText={shift.data === null ? t("shift.none") : t("detail.noDowntime")}
      >
        {downtime.data && <DowntimeTable events={downtime.data.results} zone={zone} />}
      </Panel>

      <MachineActions machineId={machineId} />
    </main>
  );
}
