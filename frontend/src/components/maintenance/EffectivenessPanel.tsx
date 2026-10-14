import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CircleMinus, Hourglass, TrendingDown, TrendingUp } from "lucide-react";
import { useState } from "react";

import { verifyAction } from "../../api/maintenance.ts";
import type { Effectiveness, EffectWindow, MaintenanceAction } from "../../api/maintenanceTypes.ts";
import { queryKeys } from "../../api/queryKeys.ts";
import type { MessageKey } from "../../i18n/en.ts";
import { t } from "../../i18n/t.ts";
import { formatDateTime } from "../../lib/time.ts";

const STATUS_STYLE: Record<string, string> = {
  improved: "bg-green-100 text-green-900",
  no_change: "bg-gray-100 text-gray-900",
  worse: "bg-red-100 text-red-900",
  not_enough_data: "bg-amber-50 text-amber-900",
  no_signature: "bg-gray-50 text-gray-700",
  not_fixed: "bg-gray-50 text-gray-700",
};
const ICONS = {
  improved: TrendingDown,
  no_change: CircleMinus,
  worse: TrendingUp,
  not_enough_data: Hourglass,
  no_signature: CircleMinus,
  not_fixed: Hourglass,
};

function Bars({ label, before, after }: { label: string; before: number | null; after: number | null }) {
  const max = Math.max(before ?? 0, after ?? 0, 0.0001);
  const row = (name: string, value: number | null, colour: string) => (
    <div className="flex items-center gap-2">
      <span className="w-14 text-base text-gray-600">{name}</span>
      <div className="h-6 flex-1 rounded bg-gray-100">
        <div className={`h-6 rounded ${colour}`} style={{ width: `${((value ?? 0) / max) * 100}%` }} />
      </div>
      <span className="w-16 text-right text-lg font-bold tabular-nums">{value ?? "–"}</span>
    </div>
  );
  return (
    <div className="flex flex-col gap-1">
      <p className="text-lg font-semibold">{label}</p>
      {row(t("maint.effect.before"), before, "bg-gray-500")}
      {row(t("maint.effect.after"), after, "bg-blue-600")}
    </div>
  );
}

/** Before vs after, per 10 run hours, worded as an observation; and the verify buttons. */
export function EffectivenessPanel({
  effect,
  action,
  canVerify,
}: {
  effect: Effectiveness;
  action: MaintenanceAction;
  canVerify: boolean;
}) {
  const queryClient = useQueryClient();
  const [note, setNote] = useState("");
  const verify = useMutation({
    mutationFn: (result: "effective" | "not_effective") => verifyAction(action.id, result, note),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: queryKeys.maintenance }),
  });
  const zone = action.factory_timezone;
  const Icon = ICONS[effect.status];
  const before: EffectWindow | undefined = effect.before;
  const after = effect.after ?? undefined;

  return (
    <div className="flex flex-col gap-3" data-testid="effectiveness">
      <p className={`flex items-center gap-2 rounded-lg p-2 text-xl font-bold ${STATUS_STYLE[effect.status]}`} data-testid="effect-status">
        <Icon aria-hidden className="h-6 w-6" />
        {t(`maint.effect.status.${effect.status}` as MessageKey)}
      </p>
      {effect.status === "no_signature" && <p className="text-lg">{t("maint.effect.noSignature")}</p>}
      {effect.status === "not_enough_data" && effect.reason && (
        <p className="text-lg" data-testid="effect-reason">
          {t(`maint.effect.reason.${effect.reason}` as MessageKey, {
            hours: effect.missing_run_hours ?? 0,
            min: effect.min_before_occurrences,
          })}
        </p>
      )}
      {effect.fixed_at && before && (
        <>
          <p className="text-base text-gray-700">
            {t("maint.effect.window", { time: formatDateTime(effect.fixed_at, zone), days: effect.window_days })}
          </p>
          <Bars label={t("maint.effect.stops")} before={before.occurrences_per_10h} after={after?.occurrences_per_10h ?? null} />
          <Bars label={t("maint.effect.downtime")} before={before.downtime_minutes_per_10h} after={after?.downtime_minutes_per_10h ?? null} />
          <p className="text-base text-gray-700">
            {t("maint.effect.counts", {
              before: before.occurrences,
              beforeHours: before.run_hours,
              after: after?.occurrences ?? 0,
              afterHours: after?.run_hours ?? 0,
            })}
          </p>
        </>
      )}
      {effect.message_key && effect.message_values && (
        <p className="text-lg font-semibold" data-testid="effect-message">
          {t(effect.message_key as MessageKey, {
            from: String(effect.message_values.from ?? ""),
            to: String(effect.message_values.to ?? ""),
          })}
        </p>
      )}
      {before && <p className="text-base italic text-gray-600">{t("maint.effect.notice")}</p>}
      {action.status === "verified" && action.verified_by && (
        <p className="text-lg font-semibold" data-testid="verified">
          {t("maint.effect.verified", {
            result: t(`maint.effect.result.${action.verification_result || "effective"}` as MessageKey),
            who: action.verified_by.email,
          })}
          {action.verification_note && ` — “${action.verification_note}”`}
        </p>
      )}
      {action.status === "done" && canVerify && (
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col text-lg">
            {t("maint.detail.note")}
            <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={4000} className="rounded-lg border border-gray-300 px-3 py-2 text-lg" />
          </label>
          <button type="button" onClick={() => verify.mutate("effective")} disabled={verify.isPending} className="min-h-14 rounded-xl bg-green-800 px-5 text-xl font-bold text-white">
            {t("maint.effect.verifyEffective")}
          </button>
          <button type="button" onClick={() => verify.mutate("not_effective")} disabled={verify.isPending} className="min-h-14 rounded-xl bg-red-800 px-5 text-xl font-bold text-white">
            {t("maint.effect.verifyNotEffective")}
          </button>
        </div>
      )}
    </div>
  );
}

