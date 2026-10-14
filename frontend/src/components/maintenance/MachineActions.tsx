import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";

import { listActions } from "../../api/maintenance.ts";
import type { MaintenanceAction } from "../../api/maintenanceTypes.ts";
import { queryKeys } from "../../api/queryKeys.ts";
import { t } from "../../i18n/t.ts";
import { STATUS_STYLE, priorityLabel, statusLabel } from "../../lib/maintenanceText.ts";
import { Panel } from "../Panel.tsx";
import { CreateActionButton } from "./CreateActionDialog.tsx";

function Row({ action }: { action: MaintenanceAction }) {
  return (
    <li className="flex flex-wrap items-center gap-2 text-lg">
      <span className={`rounded px-2 text-base font-semibold ${STATUS_STYLE[action.status]}`}>{statusLabel(action.status)}</span>
      <Link to={`/maintenance/${action.id}`} className="text-blue-900 underline">
        #{action.id} {action.title}
      </Link>
      <span className="text-gray-600">
        {priorityLabel(action.priority)}
        {action.is_overdue && ` · ${t("maint.overdue")}`}
      </span>
    </li>
  );
}

/** The machine page's maintenance: open actions, the latest completed ones, "Create action". */
export function MachineActions({ machineId }: { machineId: number }) {
  const open = useQuery({
    queryKey: queryKeys.maintenanceList({ machine: machineId, status: "open" }),
    queryFn: () => listActions({ machine: machineId, status: "open", limit: 20 }),
  });
  const recent = useQuery({
    queryKey: queryKeys.maintenanceList({ machine: machineId, status: "done,verified" }),
    queryFn: () => listActions({ machine: machineId, status: "done,verified", limit: 5 }),
  });
  return (
    <Panel title={t("maint.machine.open")} isLoading={open.isLoading} isError={open.isError}>
      <div className="mb-3">
        <CreateActionButton source={{ source: "machine", id: machineId }} />
      </div>
      {open.data?.results.length === 0 && <p className="text-lg text-gray-600">{t("maint.machine.none")}</p>}
      <ul className="flex flex-col gap-1" data-testid="machine-open-actions">
        {(open.data?.results ?? []).map((a) => (
          <Row key={a.id} action={a} />
        ))}
      </ul>
      <h3 className="mt-4 text-lg font-semibold">{t("maint.machine.recent")}</h3>
      {recent.data?.results.length === 0 && <p className="text-lg text-gray-600">{t("maint.machine.none")}</p>}
      <ul className="flex flex-col gap-1">
        {(recent.data?.results ?? []).map((a) => (
          <Row key={a.id} action={a} />
        ))}
      </ul>
    </Panel>
  );
}
