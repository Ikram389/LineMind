import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useParams } from "react-router";

import { listDowntimeEvents } from "../api/downtime.ts";
import { queryKeys } from "../api/queryKeys.ts";
import { ClassifyPanel } from "../components/ClassifyPanel.tsx";
import { LineNav } from "../components/LineNav.tsx";
import { Panel } from "../components/Panel.tsx";
import { QuickClassifyCard } from "../components/QuickClassifyCard.tsx";
import { t } from "../i18n/t.ts";
import type { ClassifyTarget } from "../lib/classifyTarget.ts";
import { usePermissions } from "../lib/permissions.ts";
import { useLineContext } from "./useLineContext.ts";

/** The current shift's stops that still need a reason (consequences never do). */
export function UnclassifiedPage() {
  const lineId = Number(useParams().lineId);
  const { factory, shift } = useLineContext(lineId);
  const { canClassify } = usePermissions();
  const [panelFor, setPanelFor] = useState<ClassifyTarget | null>(null);
  const zone = factory.data?.timezone ?? "UTC";

  const queue = useQuery({
    queryKey: [...queryKeys.unclassified(lineId), "list", shift.data?.start],
    queryFn: () =>
      listDowntimeEvents({
        line: lineId,
        start: shift.data?.start,
        end: shift.data?.end,
        needs_reason: true,
        classified: false,
        limit: 200,
      }),
    enabled: Boolean(shift.data),
  });

  return (
    <main className="flex min-h-screen flex-col gap-4 bg-gray-100 p-4">
      <h1 className="text-3xl font-bold">{t("queue.title")}</h1>
      <LineNav lineId={lineId} shift={shift.data} />
      <Panel
        title={shift.data?.label}
        isLoading={queue.isLoading}
        isError={queue.isError}
        isEmpty={shift.data === null || queue.data?.results.length === 0}
        emptyText={shift.data === null ? t("queue.noShift") : t("queue.empty")}
      >
        <ul className="flex flex-col gap-4">
          {queue.data?.results.map((event) => (
            <li key={event.id}>
              {canClassify ? (
                <QuickClassifyCard event={event} buttons={4} onMore={() => setPanelFor(event)} />
              ) : (
                <p className="text-lg">{event.machine.name}</p>
              )}
            </li>
          ))}
        </ul>
      </Panel>
      {panelFor && factory.data && (
        <ClassifyPanel
          events={[panelFor]}
          factoryId={factory.data.id}
          zone={zone}
          onClose={() => setPanelFor(null)}
        />
      )}
    </main>
  );
}
