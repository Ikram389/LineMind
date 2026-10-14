import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { X } from "lucide-react";
import { useState } from "react";

import { ApiError } from "../../api/client.ts";
import { getReviews, listDefectTypes, reviewResult } from "../../api/quality.ts";
import type { InspectionResult, Verdict } from "../../api/qualityTypes.ts";
import { queryKeys } from "../../api/queryKeys.ts";
import { CreateActionButton } from "../maintenance/CreateActionDialog.tsx";
import type { MessageKey } from "../../i18n/en.ts";
import { t } from "../../i18n/t.ts";
import { reviewLabel } from "../../lib/qualityFormat.ts";
import { formatDateTime } from "../../lib/time.ts";

interface ReviewPanelProps {
  result: InspectionResult;
  zone: string;
  canReview: boolean;
  onClose: () => void;
  onSaved?: (label: string) => void;
}

const VERDICTS: { key: Verdict; label: MessageKey; style: string }[] = [
  { key: "confirmed", label: "review.confirm", style: "border-green-700 bg-green-700" },
  { key: "false_reject", label: "review.falseReject", style: "border-blue-800 bg-blue-800" },
  { key: "reclassified", label: "review.reclassify", style: "border-purple-800 bg-purple-800" },
];

function errorText(error: unknown): string {
  if (error instanceof ApiError && error.body && typeof error.body === "object") {
    return Object.values(error.body as Record<string, unknown>).flat().join(" ");
  }
  return String(error);
}

/** A bottom sheet for tablets: Confirm / False reject / Reclassify, comment, history. */
export function ReviewPanel({ result, zone, canReview, onClose, onSaved }: ReviewPanelProps) {
  const queryClient = useQueryClient();
  const [verdict, setVerdict] = useState<Verdict | null>(null);
  const [corrected, setCorrected] = useState<number | null>(null);
  const [comment, setComment] = useState("");

  const history = useQuery({
    queryKey: ["qualityReviews", result.id],
    queryFn: () => getReviews(result.id),
  });
  const types = useQuery({
    queryKey: queryKeys.defectTypes(),
    queryFn: () => listDefectTypes(),
    enabled: canReview && verdict === "reclassified",
  });
  const save = useMutation({
    mutationFn: () => reviewResult(result.id, verdict as Verdict, verdict === "reclassified" ? corrected : null, comment),
    onSuccess: (review) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.quality });
      void queryClient.invalidateQueries({ queryKey: ["qualityReviews", result.id] });
      onSaved?.(reviewLabel({ review }));
      onClose();
    },
  });

  const detected = result.defect_type
    ? `${result.defect_type.code} · ${result.defect_type.name}`
    : t("qtable.unknownType", { code: result.reported_code || "–" });
  const ready = verdict !== null && (verdict !== "reclassified" || corrected !== null);
  const choices = (types.data ?? []).filter((d) => d.id !== result.defect_type?.id);

  return (
    <div className="fixed inset-0 z-40 flex items-end justify-center bg-black/40" role="presentation">
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby="review-title"
        className="max-h-[92vh] w-full max-w-3xl overflow-y-auto rounded-t-2xl bg-white p-5 shadow-2xl"
      >
        <header className="mb-3 flex items-start justify-between gap-3">
          <div>
            <h2 id="review-title" className="text-2xl font-bold">
              {t("review.title")}: {detected}
            </h2>
            <p className="text-lg text-gray-700">
              {t("review.detected", {
                code: result.reported_code || "–",
                station: result.station?.name ?? result.machine.name,
                time: formatDateTime(result.timestamp, zone),
              })}
              {" · "}
              {result.confidence === null
                ? t("review.noConfidence")
                : t("review.confidence", { value: result.confidence.toFixed(2) })}
            </p>
            {result.context?.incident && <p className="text-lg text-gray-700">{result.context.incident.text}</p>}
            <p className="text-lg font-semibold">{t("review.current", { verdict: reviewLabel(result) })}</p>
            <div className="mt-2">
              <CreateActionButton source={{ source: "inspection_result", id: result.id }} compact />
            </div>
          </div>
          <button type="button" onClick={onClose} aria-label={t("review.close")} className="p-2">
            <X aria-hidden className="h-8 w-8" />
          </button>
        </header>

        {canReview ? (
          <div className="flex flex-col gap-4">
            <div className="grid grid-cols-3 gap-3" role="group" aria-label={t("qtable.review")}>
              {VERDICTS.map((v) => (
                <button
                  key={v.key}
                  type="button"
                  aria-pressed={verdict === v.key}
                  onClick={() => setVerdict(v.key)}
                  className={`min-h-16 rounded-xl border-2 px-3 text-xl font-bold ${
                    verdict === v.key ? `${v.style} text-white` : "border-gray-300 bg-white text-gray-900"
                  }`}
                >
                  {t(v.label)}
                </button>
              ))}
            </div>
            {verdict === "reclassified" && (
              <fieldset className="flex flex-col gap-2">
                <legend className="mb-1 text-lg font-semibold">{t("review.chooseType")}</legend>
                <div className="grid gap-2 sm:grid-cols-2">
                  {choices.map((d) => (
                    <button
                      key={d.id}
                      type="button"
                      aria-pressed={corrected === d.id}
                      onClick={() => setCorrected(d.id)}
                      className={`min-h-14 rounded-lg border-2 px-3 text-left text-lg ${
                        corrected === d.id ? "border-purple-800 bg-purple-50 font-semibold" : "border-gray-300"
                      }`}
                    >
                      {d.code} · {d.name}
                    </button>
                  ))}
                </div>
              </fieldset>
            )}
            <label className="flex flex-col gap-1 text-lg">
              {t("review.comment")}
              <textarea
                value={comment}
                onChange={(e) => setComment(e.target.value)}
                rows={2}
                maxLength={1000}
                className="rounded-lg border border-gray-300 p-2 text-lg"
              />
            </label>
            <p className="text-base text-gray-600">{t("review.oeeNote")}</p>
            {save.isError && (
              <p role="alert" className="text-lg text-red-700">
                {t("review.failed", { message: errorText(save.error) })}
              </p>
            )}
            <button
              type="button"
              disabled={!ready || save.isPending}
              onClick={() => save.mutate()}
              className="min-h-14 rounded-xl bg-gray-900 text-xl font-bold text-white disabled:opacity-40"
            >
              {save.isPending ? t("review.saving") : t("review.save")}
            </button>
          </div>
        ) : (
          <p className="text-lg text-gray-700">{t("review.readOnly")}</p>
        )}

        <section className="mt-5">
          <h3 className="mb-2 text-lg font-semibold">{t("review.history")}</h3>
          {history.data && history.data.length > 0 ? (
            <ol className="flex flex-col gap-1 text-lg" data-testid="review-history">
              {history.data.map((h) => (
                <li key={h.id}>
                  {t("review.historyRow", {
                    verdict: reviewLabel({ review: h }),
                    who: h.reviewed_by,
                    time: formatDateTime(h.reviewed_at, zone),
                  })}
                  {h.comment && ` — “${h.comment}”`}
                </li>
              ))}
            </ol>
          ) : (
            <p className="text-lg text-gray-600">{t("review.noHistory")}</p>
          )}
        </section>
      </section>
    </div>
  );
}
