import { useQuery } from "@tanstack/react-query";
import { Minimize, Tv } from "lucide-react";
import { useCallback, useState } from "react";
import { useParams, useSearchParams } from "react-router";

import { getLineStatus, getOee } from "../api/endpoints.ts";
import type { LiveMessage } from "../api/types.ts";
import { queryKeys } from "../api/queryKeys.ts";
import { AlertBanner } from "../components/alerts/AlertBanner.tsx";
import { ClassifyPanel } from "../components/ClassifyPanel.tsx";
import { Header } from "../components/Header.tsx";
import { IncidentBanner } from "../components/IncidentBanner.tsx";
import { UnclassifiedBadge } from "../components/LineNav.tsx";
import { LiveIndicator } from "../components/LiveIndicator.tsx";
import { MachineFlow } from "../components/MachineFlow.tsx";
import { OeeHourlyChart } from "../components/OeeHourlyChart.tsx";
import { OeePanel } from "../components/OeePanel.tsx";
import { Panel } from "../components/Panel.tsx";
import { QualityCard } from "../components/quality/QualityCard.tsx";
import { QuickClassifyCard } from "../components/QuickClassifyCard.tsx";
import { Button } from "../components/ui/Button.tsx";
import { Toast } from "../components/ui/Toast.tsx";
import { t } from "../i18n/t.ts";
import type { ClassifyTarget } from "../lib/classifyTarget.ts";
import { usePermissions } from "../lib/permissions.ts";
import { serverNow, useServerNow } from "../lib/serverClock.ts";
import { useAlertBanners } from "../live/useAlertBanners.ts";
import { useClassificationPrompts } from "../live/useClassificationPrompts.ts";
import { useLineLive } from "../live/useLineLive.ts";
import { useLineContext } from "./useLineContext.ts";

const POLL_WHEN_DISCONNECTED_MS = 15_000;
const OEE_REFRESH_MS = 60_000;

export function LineOverviewPage() {
  const lineId = Number(useParams().lineId);
  const nowMs = useServerNow();
  const { prompts, onMessage, dismiss } = useClassificationPrompts();
  const banners = useAlertBanners(lineId);
  const onAlertMessage = banners.onMessage;
  const onLiveMessage = useCallback(
    (message: LiveMessage) => {
      onMessage(message);
      onAlertMessage(message);
    },
    [onMessage, onAlertMessage],
  );
  const live = useLineLive(lineId, onLiveMessage);
  const { canClassify } = usePermissions();
  const [panelFor, setPanelFor] = useState<ClassifyTarget | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const hideSaved = useCallback(() => setSaved(null), []);
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
    <main className="flex flex-col gap-6 p-4 sm:p-6">
      <Header
        factoryName={factory.data?.name ?? ""}
        lineName={line.data?.name ?? ""}
        zone={zone}
        shift={shift.data}
        nowMs={nowMs}
        actions={
          <>
            <LiveIndicator status={live} />
            <UnclassifiedBadge lineId={lineId} shift={shift.data} />
            <TvButton />
          </>
        }
      />

      {banners.banners.map((alert) => (
        <AlertBanner key={alert.alert_id} alert={alert} zone={zone} onHide={() => banners.hide(alert.alert_id)} />
      ))}
      {incident && <IncidentBanner incident={incident} nowMs={nowMs} />}

      <Panel title={t("overview.machines")} isLoading={status.isLoading} isError={status.isError && !status.data}>
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

      <div className="grid gap-6 xl:grid-cols-2">
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

      <QualityCard lineId={lineId} shift={shift.data} />

      {saved && <Toast message={t("classify.saved", { reason: saved })} onClose={hideSaved} />}
      {canClassify && prompts[0] && (
        <aside className="fixed bottom-4 right-4 z-30 w-[min(44rem,calc(100vw-2rem))]">
          <QuickClassifyCard
            key={prompts[0].id}
            event={prompts[0]}
            onMore={() => setPanelFor(prompts[0] ?? null)}
            onLater={() => dismiss(prompts[0]?.id ?? 0)}
            onDone={(reason) => {
              setSaved(reason);
              dismiss(prompts[0]?.id ?? 0);
            }}
          />
        </aside>
      )}
      {panelFor && factory.data && (
        <ClassifyPanel
          events={[panelFor]}
          factoryId={factory.data.id}
          zone={zone}
          onClose={() => setPanelFor(null)}
          onSaved={(reason) => {
            setSaved(reason);
            dismiss(panelFor.id);
          }}
        />
      )}
    </main>
  );
}

/** Opens TV mode (full screen, no menus) or, in TV mode, leaves it. */
function TvButton() {
  const [params, setParams] = useSearchParams();
  const tv = params.get("tv") === "1";
  if (tv) {
    return (
      <Button
        variant="ghost"
        icon={<Minimize aria-hidden className="h-5 w-5" />}
        onClick={() => {
          if (document.fullscreenElement) void document.exitFullscreen?.().catch(() => undefined);
          setParams({});
        }}
      >
        {t("tv.exit")}
      </Button>
    );
  }
  return (
    <Button
      icon={<Tv aria-hidden className="h-5 w-5" />}
      onClick={() => {
        void document.documentElement.requestFullscreen?.().catch(() => undefined);
        setParams({ tv: "1" });
      }}
    >
      {t("tv.open")}
    </Button>
  );
}
