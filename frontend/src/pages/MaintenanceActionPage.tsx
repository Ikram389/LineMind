import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router";

import { getAction, getEffectiveness, getHistory, listLinks } from "../api/maintenance.ts";
import { queryKeys } from "../api/queryKeys.ts";
import { useAuth } from "../auth/context.ts";
import { IncidentDrawer } from "../components/downtime/IncidentDrawer.tsx";
import { DiagnosisForm } from "../components/maintenance/DiagnosisForm.tsx";
import { EffectivenessPanel } from "../components/maintenance/EffectivenessPanel.tsx";
import { EvidenceTimeline } from "../components/maintenance/EvidenceTimeline.tsx";
import { StepPanel } from "../components/maintenance/StepPanel.tsx";
import { WorkLog } from "../components/maintenance/WorkLog.tsx";
import { Panel } from "../components/Panel.tsx";
import type { MessageKey } from "../i18n/en.ts";
import { t } from "../i18n/t.ts";
import { PRIORITY_STYLE, priorityLabel } from "../lib/maintenanceText.ts";
import { usePermissions } from "../lib/permissions.ts";
import { formatDateTime } from "../lib/time.ts";

const WORKING = new Set(["assigned", "in_progress", "waiting", "done"]);
const DIAGNOSABLE = new Set(["in_progress", "waiting", "done"]);

/** One action: next steps, evidence, work log, confirmed diagnosis and before/after. */
export function MaintenanceActionPage() {
  const id = Number(useParams().actionId);
  const { user } = useAuth();
  const { canPlanMaintenance, isTechnician } = usePermissions();
  const [drawer, setDrawer] = useState<number | null>(null);
  const action = useQuery({ queryKey: queryKeys.maintenanceAction(id), queryFn: () => getAction(id) });
  const links = useQuery({ queryKey: [...queryKeys.maintenanceAction(id), "links"], queryFn: () => listLinks(id) });
  const history = useQuery({ queryKey: [...queryKeys.maintenanceAction(id), "history"], queryFn: () => getHistory(id) });
  const effect = useQuery({ queryKey: [...queryKeys.maintenanceAction(id), "effect"], queryFn: () => getEffectiveness(id) });

  if (action.isLoading) return <p className="p-6 text-lg">{t("panel.loading")}</p>;
  if (!action.data) return <p className="p-6 text-lg text-red-700">{t("panel.error")}</p>;
  const a = action.data;
  const zone = a.factory_timezone;
  const isWorker = isTechnician || (user !== null && a.assignee === user?.id);

  return (
    <main className="flex min-h-screen flex-col gap-4 bg-gray-100 p-4">
      <Link to="/maintenance" className="text-lg text-blue-800 underline">
        ← {t("maint.title")}
      </Link>
      <header className="rounded-xl bg-white p-4 shadow-sm">
        <h1 className="text-3xl font-bold">
          #{a.id} {a.title}
        </h1>
        <p className="text-lg text-gray-700">
          {t(`mtype.${a.action_type}` as MessageKey)} ·{" "}
          <span className={`rounded px-2 ${PRIORITY_STYLE[a.priority]}`}>{priorityLabel(a.priority)}</span> ·{" "}
          <Link to={`/lines/${a.line}/machines/${a.machine}`} className="underline">
            {a.machine_name}
          </Link>
          , {a.line_name} · {a.due_date ? t("maint.due", { date: a.due_date }) : t("maint.noDue")}
          {a.is_overdue && <strong className="ml-2 text-red-700">{t("maint.overdue")}</strong>} ·{" "}
          {a.assignee_detail ? t("maint.assignee", { who: a.assignee_detail.email }) : t("maint.unassigned")} ·{" "}
          {t("maint.reportedBy", { who: a.reporter.email })}
        </p>
        {a.problem && (
          <p className="mt-2 text-lg">
            <strong>{t("maint.detail.problem")}:</strong> {a.problem}
          </p>
        )}
      </header>

      <StepPanel action={a} />

      <div className="grid gap-4 xl:grid-cols-2">
        <Panel title={t("maint.evidence")} isLoading={links.isLoading} isError={links.isError}>
          {links.data && <EvidenceTimeline action={a} links={links.data} onOpenIncident={setDrawer} />}
        </Panel>
        <Panel title={t("maint.log")}>
          <WorkLog actionId={a.id} zone={zone} canWrite={isWorker && WORKING.has(a.status)} />
        </Panel>
      </div>

      <Panel title={t("maint.diag.title")}>
        <DiagnosisForm
          actionId={a.id}
          factoryId={a.factory}
          current={history.data?.diagnoses[0]}
          canWrite={isWorker && DIAGNOSABLE.has(a.status)}
        />
      </Panel>

      <Panel title={t("maint.effect.title")} isLoading={effect.isLoading} isError={effect.isError}>
        {effect.data && <EffectivenessPanel effect={effect.data} action={a} canVerify={canPlanMaintenance} />}
      </Panel>

      <Panel title={t("maint.detail.history")}>
        <ol className="flex flex-col gap-1 text-lg">
          {(history.data?.status_changes ?? []).map((c) => (
            <li key={c.id}>
              {formatDateTime(c.changed_at, zone)} · {c.changed_by.email}: {t(`mstatus.${c.from_status}` as MessageKey)} →{" "}
              {t(`mstatus.${c.to_status}` as MessageKey)}
              {c.note && ` — “${c.note}”`}
            </li>
          ))}
        </ol>
      </Panel>
      {drawer !== null && <IncidentDrawer incidentId={drawer} zone={zone} onClose={() => setDrawer(null)} />}
    </main>
  );
}
