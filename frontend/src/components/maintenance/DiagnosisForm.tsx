import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";

import { listReasons } from "../../api/downtime.ts";
import { previewDiagnosis, recordDiagnosis } from "../../api/maintenance.ts";
import type { Diagnosis } from "../../api/maintenanceTypes.ts";
import { queryKeys } from "../../api/queryKeys.ts";
import { t } from "../../i18n/t.ts";

const field = "rounded-lg border border-gray-300 bg-white px-3 py-2 text-lg";

/** The confirmed diagnosis. Before applying it to the linked stops, a preview says what would
 * change; reasons operators chose in another category are kept unless asked otherwise. */
export function DiagnosisForm({
  actionId,
  factoryId,
  current,
  canWrite,
}: {
  actionId: number;
  factoryId: number;
  current: Diagnosis | undefined;
  canWrite: boolean;
}) {
  const queryClient = useQueryClient();
  const [reason, setReason] = useState<number | null>(null);
  const [text, setText] = useState("");
  const [apply, setApply] = useState(true);
  const [replace, setReplace] = useState(false);
  const reasons = useQuery({ queryKey: queryKeys.reasons(factoryId), queryFn: () => listReasons(factoryId), enabled: canWrite });
  const preview = useQuery({
    queryKey: ["diagnosisPreview", actionId, reason],
    queryFn: () => previewDiagnosis(actionId, reason ?? 0),
    enabled: canWrite && reason !== null,
  });
  const save = useMutation({
    mutationFn: () =>
      recordDiagnosis(actionId, { reason: reason ?? 0, text, apply_to_linked_stops: apply, replace_other_reasons: apply && replace }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.maintenanceAction(actionId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.downtime });
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    if (reason !== null) save.mutate();
  }

  const p = preview.data;
  return (
    <div className="flex flex-col gap-3">
      {current && (
        <p className="text-lg" data-testid="current-diagnosis">
          {t("maint.diag.current", { code: current.reason.code, name: current.reason.name, text: current.text || "–" })}
        </p>
      )}
      {save.data && (
        <p role="status" className="rounded-lg bg-green-50 p-2 text-lg text-green-900">
          {t("maint.diag.saved", { applied: save.data.applied_count, skipped: save.data.skipped_count })}
        </p>
      )}
      {canWrite && (
        <form onSubmit={submit} className="flex flex-col gap-3" aria-label={t("maint.diag.title")}>
          <div className="flex flex-wrap gap-3">
            <label className="flex flex-col text-lg">
              {t("maint.diag.reason")}
              <select value={reason ?? ""} onChange={(e) => setReason(e.target.value ? Number(e.target.value) : null)} className={field}>
                <option value="" />
                {(reasons.data ?? []).map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.code} · {r.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-1 flex-col text-lg">
              {t("maint.diag.text")}
              <input value={text} onChange={(e) => setText(e.target.value)} maxLength={4000} className={field} />
            </label>
          </div>
          <label className="flex items-center gap-2 text-lg">
            <input type="checkbox" checked={apply} onChange={(e) => setApply(e.target.checked)} className="h-6 w-6" />
            {t("maint.diag.apply")}
          </label>
          {apply && p && (
            <div className="rounded-lg bg-blue-50 p-3 text-lg text-blue-950" data-testid="diagnosis-preview">
              <p>
                {t("maint.diag.preview", {
                  linked: p.linked_stops,
                  unclassified: p.unclassified,
                  same: p.same_reason,
                  category: p.same_category,
                })}
              </p>
              {p.other_reasons.length > 0 && (
                <>
                  <p>{t("maint.diag.others", { list: p.other_reasons.map((o) => `${o.name} (${o.count})`).join(", ") })}</p>
                  <label className="mt-1 flex items-center gap-2">
                    <input type="checkbox" checked={replace} onChange={(e) => setReplace(e.target.checked)} className="h-6 w-6" />
                    {t("maint.diag.replace")}
                  </label>
                </>
              )}
              <p className="font-semibold">
                {t("maint.diag.willApply", { count: replace ? p.would_apply_with_replace : p.would_apply })}
              </p>
            </div>
          )}
          <button type="submit" disabled={reason === null || save.isPending} className="min-h-14 rounded-xl bg-gray-900 text-xl font-bold text-white disabled:opacity-40">
            {t("maint.diag.save")}
          </button>
        </form>
      )}
    </div>
  );
}
