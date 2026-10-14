import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Wrench, X } from "lucide-react";
import { type FormEvent, useEffect, useState } from "react";
import { useNavigate } from "react-router";

import { ApiError } from "../../api/client.ts";
import { createAction, getPrefill } from "../../api/maintenance.ts";
import { ACTION_TYPES, type ActionType, type PrefillSource } from "../../api/maintenanceTypes.ts";
import { queryKeys } from "../../api/queryKeys.ts";
import type { MessageKey } from "../../i18n/en.ts";
import { t } from "../../i18n/t.ts";
import { usePermissions } from "../../lib/permissions.ts";

const field = "rounded-lg border border-gray-300 bg-white px-3 py-2 text-lg";

function errorText(error: unknown): string {
  if (error instanceof ApiError && error.body && typeof error.body === "object") {
    return Object.values(error.body as Record<string, unknown>).flat().join(" ");
  }
  return String(error);
}

/** "New maintenance action", pre-filled from what the person was looking at. */
export function CreateActionDialog({ source, onClose }: { source: PrefillSource; onClose: () => void }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const prefill = useQuery({ queryKey: ["maintenancePrefill", source], queryFn: () => getPrefill(source) });
  const [title, setTitle] = useState("");
  const [problem, setProblem] = useState("");
  const [actionType, setActionType] = useState<ActionType>("corrective");
  useEffect(() => {
    if (prefill.data) {
      setTitle(prefill.data.title);
      setProblem(prefill.data.problem);
    }
  }, [prefill.data]);

  const create = useMutation({
    mutationFn: () => {
      if (!prefill.data) throw new Error("The form is not ready yet.");
      return createAction({
        machine: prefill.data.machine,
        title,
        problem,
        action_type: actionType,
        links: prefill.data.links,
      });
    },
    onSuccess: (action) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.maintenance });
      onClose();
      navigate(`/maintenance/${action.id}`);
    },
  });

  const links = prefill.data?.links ?? [];
  const stops = links.filter((l) => l.kind === "downtime_event").length;
  const others = links.filter((l) => l.kind !== "downtime_event" && l.kind !== "signature").length;
  const summary = [
    links.some((l) => l.kind === "signature") && t("maint.linkSummary.signature"),
    stops > 0 && t("maint.linkSummary.stops", { count: stops }),
    others > 0 && t("maint.linkSummary.other", { count: others }),
  ]
    .filter(Boolean)
    .join(", ");

  function submit(event: FormEvent) {
    event.preventDefault();
    create.mutate();
  }

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/40" role="presentation">
      <section role="dialog" aria-modal="true" aria-labelledby="new-action-title" className="w-full max-w-3xl rounded-t-2xl bg-white p-5 shadow-2xl">
        <header className="mb-3 flex items-start justify-between">
          <h2 id="new-action-title" className="flex items-center gap-2 text-2xl font-bold">
            <Wrench aria-hidden className="h-7 w-7" />
            {t("maint.dialogTitle")}
          </h2>
          <button type="button" onClick={onClose} aria-label={t("maint.cancel")} className="p-2">
            <X aria-hidden className="h-8 w-8" />
          </button>
        </header>
        {prefill.isLoading && <p className="text-lg">{t("panel.loading")}</p>}
        {prefill.isError && <p role="alert" className="text-lg text-red-700">{errorText(prefill.error)}</p>}
        {prefill.data && (
          <form onSubmit={submit} className="flex flex-col gap-3">
            <p className="text-lg font-semibold" data-testid="new-action-machine">
              {t("maint.machine", { machine: prefill.data.machine_name, line: prefill.data.line_name })}
            </p>
            <label className="flex flex-col text-lg">
              {t("maint.field.title")}
              <input required value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} className={field} />
            </label>
            <label className="flex flex-col text-lg">
              {t("maint.field.problem")}
              <textarea value={problem} onChange={(e) => setProblem(e.target.value)} rows={3} className={field} />
            </label>
            <fieldset className="flex flex-wrap gap-4">
              <legend className="text-lg">{t("maint.field.type")}</legend>
              {ACTION_TYPES.map((type) => (
                <label key={type} className="flex items-center gap-2 text-lg">
                  <input type="radio" name="action-type" checked={actionType === type} onChange={() => setActionType(type)} className="h-5 w-5" />
                  {t(`mtype.${type}` as MessageKey)}
                </label>
              ))}
            </fieldset>
            {summary && (
              <p className="rounded-lg bg-blue-50 p-2 text-lg text-blue-900" data-testid="new-action-links">
                {t("maint.willLink", { summary })}
              </p>
            )}
            {create.isError && <p role="alert" className="text-lg text-red-700">{t("maint.failed", { message: errorText(create.error) })}</p>}
            <div className="flex gap-3">
              <button type="submit" disabled={create.isPending || !title.trim()} className="min-h-14 rounded-xl bg-blue-700 px-6 text-xl font-bold text-white">
                {t("maint.save")}
              </button>
              <button type="button" onClick={onClose} className="min-h-14 rounded-xl border-2 border-gray-400 px-6 text-xl">
                {t("maint.cancel")}
              </button>
            </div>
          </form>
        )}
      </section>
    </div>
  );
}

/** The "Create action" button used next to stops, alerts, recurring stops, defects, machines. */
export function CreateActionButton({ source, compact = false }: { source: PrefillSource; compact?: boolean }) {
  const { canRequestMaintenance } = usePermissions();
  const [open, setOpen] = useState(false);
  if (!canRequestMaintenance) return null;
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className={`inline-flex items-center gap-2 rounded-lg border-2 border-blue-700 font-semibold text-blue-800 ${
          compact ? "min-h-10 px-2 text-base" : "min-h-12 px-4 text-lg"
        }`}
      >
        <Wrench aria-hidden className="h-5 w-5" />
        {t("maint.create")}
      </button>
      {open && <CreateActionDialog source={source} onClose={() => setOpen(false)} />}
    </>
  );
}
