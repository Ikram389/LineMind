import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleCheck, Circle, CircleDot } from "lucide-react";
import { useState } from "react";

import { ApiError } from "../../api/client.ts";
import { listAssignees, transitionAction, verifyAction } from "../../api/maintenance.ts";
import { type AllowedStep, type MaintenanceAction, STATUS_PATH } from "../../api/maintenanceTypes.ts";
import { queryKeys } from "../../api/queryKeys.ts";
import type { MessageKey } from "../../i18n/en.ts";
import { t } from "../../i18n/t.ts";
import { STATUS_STYLE, statusLabel } from "../../lib/maintenanceText.ts";
import { fromLocalInput } from "../../lib/zonedTime.ts";

const field = "rounded-lg border border-gray-300 bg-white px-3 py-2 text-lg";

function errorText(error: unknown): string {
  if (error instanceof ApiError && error.body && typeof error.body === "object") {
    return Object.values(error.body as Record<string, unknown>).flat().join(" ");
  }
  return String(error);
}

/** The path requested → assigned → in progress → done → verified, then only the steps this
 * user may take now (from the backend) as buttons. */
export function StepPanel({ action }: { action: MaintenanceAction }) {
  const queryClient = useQueryClient();
  const [chosen, setChosen] = useState<AllowedStep | null>(null);
  const [note, setNote] = useState("");
  const [assignee, setAssignee] = useState<number | null>(action.assignee);
  const [fixedLocal, setFixedLocal] = useState("");
  const people = useQuery({
    queryKey: ["maintenanceAssignees", action.id],
    queryFn: () => listAssignees(action.id),
    enabled: chosen?.event === "assign",
  });
  const done = () => {
    setChosen(null);
    setNote("");
    void queryClient.invalidateQueries({ queryKey: queryKeys.maintenance });
  };
  const step = useMutation({
    mutationFn: (s: AllowedStep) =>
      transitionAction(action.id, {
        to: s.to,
        note,
        assignee: s.event === "assign" ? assignee : undefined,
        fixed_at: s.event === "complete" && fixedLocal ? fromLocalInput(fixedLocal, action.factory_timezone) : undefined,
      }),
    onSuccess: done,
  });
  const verify = useMutation({
    mutationFn: (result: "effective" | "not_effective") => verifyAction(action.id, result, note),
    onSuccess: done,
  });
  const steps = action.allowed_steps.filter((s) => s.event !== "verify");
  const pathIndex = STATUS_PATH.indexOf(action.status);
  const needsForm = (s: AllowedStep) => s.note_required || ["assign", "complete", "verify"].includes(s.event);

  return (
    <section aria-label={t("maint.detail.next")} className="flex flex-col gap-3 rounded-xl bg-white p-4 shadow-sm">
      <ol className="flex flex-wrap items-center gap-2" data-testid="status-path">
        {STATUS_PATH.map((status, index) => {
          const Icon = index < pathIndex ? CircleCheck : index === pathIndex ? CircleDot : Circle;
          return (
            <li
              key={status}
              aria-current={status === action.status ? "step" : undefined}
              className={`flex items-center gap-1 rounded-full px-3 py-1 text-lg ${status === action.status ? STATUS_STYLE[status] + " font-bold" : "text-gray-600"}`}
            >
              <Icon aria-hidden className="h-5 w-5" />
              {statusLabel(status)}
            </li>
          );
        })}
        {pathIndex === -1 && (
          <li aria-current="step" className={`rounded-full px-3 py-1 text-lg font-bold ${STATUS_STYLE[action.status]}`}>
            {statusLabel(action.status)}
          </li>
        )}
      </ol>
      <div className="flex flex-wrap items-center gap-2" data-testid="next-steps">
        <span className="text-lg font-semibold">{t("maint.detail.next")}</span>
        {steps.length === 0 && <span className="text-lg text-gray-600">{t("maint.detail.noNext")}</span>}
        {steps.map((s) => (
          <button
            key={`${s.event}-${s.to}`}
            type="button"
            onClick={() => (needsForm(s) ? setChosen(s) : step.mutate(s))}
            aria-pressed={chosen?.to === s.to}
            className="min-h-14 rounded-xl bg-gray-900 px-5 text-xl font-bold text-white"
          >
            {t(`mstep.${s.event}` as MessageKey)}
          </button>
        ))}
      </div>
      {chosen && (
        <div className="flex flex-wrap items-end gap-3 rounded-lg border border-gray-300 p-3">
          {chosen.event === "assign" && (
            <label className="flex flex-col text-lg">
              {t("maint.detail.assignTo")}
              <select value={assignee ?? ""} onChange={(e) => setAssignee(e.target.value ? Number(e.target.value) : null)} className={field}>
                <option value="" />
                {(people.data ?? []).map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.email} ({t(`roleName.${p.role}` as MessageKey)})
                  </option>
                ))}
              </select>
            </label>
          )}
          {chosen.event === "complete" && (
            <label className="flex flex-col text-lg">
              {t("maint.detail.fixedAt")}
              <input type="datetime-local" value={fixedLocal} onChange={(e) => setFixedLocal(e.target.value)} className={field} />
            </label>
          )}
          <label className="flex flex-col text-lg">
            {chosen.note_required ? t("maint.detail.noteRequired") : t("maint.detail.note")}
            <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={4000} className={field} />
          </label>
          {chosen.event === "verify" ? (
            <>
              <button type="button" onClick={() => verify.mutate("effective")} className="min-h-12 rounded-lg bg-green-800 px-4 text-lg font-semibold text-white">
                {t("maint.effect.verifyEffective")}
              </button>
              <button type="button" onClick={() => verify.mutate("not_effective")} className="min-h-12 rounded-lg bg-red-800 px-4 text-lg font-semibold text-white">
                {t("maint.effect.verifyNotEffective")}
              </button>
            </>
          ) : (
            <button
              type="button"
              disabled={(chosen.note_required && !note.trim()) || (chosen.event === "assign" && assignee === null) || step.isPending}
              onClick={() => step.mutate(chosen)}
              className="min-h-12 rounded-lg bg-blue-700 px-4 text-lg font-semibold text-white disabled:opacity-40"
            >
              {t("maint.detail.confirm")}
            </button>
          )}
          <button type="button" onClick={() => setChosen(null)} className="min-h-12 rounded-lg border border-gray-400 px-4 text-lg">
            {t("maint.cancel")}
          </button>
        </div>
      )}
      {(step.isError || verify.isError) && (
        <p role="alert" className="text-lg text-red-700">
          {t("maint.failed", { message: errorText(step.error ?? verify.error) })}
        </p>
      )}
    </section>
  );
}
