import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";
import { useMemo, useState } from "react";

import { getClassifications, getSuggestedReasons, listReasons } from "../api/downtime.ts";
import { queryKeys } from "../api/queryKeys.ts";
import type { MessageKey } from "../i18n/en.ts";
import { t } from "../i18n/t.ts";
import type { ClassifyTarget } from "../lib/classifyTarget.ts";
import { groupReasons, matchesSearch } from "../lib/reasonOrder.ts";
import { formatDateTime, formatDuration } from "../lib/time.ts";
import { useClassify } from "../lib/useClassify.ts";

interface ClassifyPanelProps {
  events: ClassifyTarget[]; // one stop, or several for bulk classification
  factoryId: number;
  zone: string;
  onClose: () => void;
  onSaved?: (reasonName: string) => void;
}

const CATEGORY_KEY: Record<string, MessageKey> = {
  breakdown: "category.breakdown",
  blocked: "category.blocked",
  starved: "category.starved",
  planned: "category.planned",
  no_data: "category.no_data",
};

/** A bottom sheet for tablets: likely reasons first, all reasons by category, search, comment. */
export function ClassifyPanel({ events, factoryId, zone, onClose, onSaved }: ClassifyPanelProps) {
  const single = events.length === 1 ? events[0] : undefined;
  const [selected, setSelected] = useState<number | null>(null);
  const [search, setSearch] = useState("");
  const [comment, setComment] = useState("");
  const classify = useClassify();

  const reasons = useQuery({
    queryKey: queryKeys.reasons(factoryId),
    queryFn: () => listReasons(factoryId),
  });
  const suggestions = useQuery({
    queryKey: ["suggestedReasons", single?.id],
    queryFn: () => getSuggestedReasons(single?.id ?? 0),
    enabled: single !== undefined,
  });
  const history = useQuery({
    queryKey: ["classifications", single?.id],
    queryFn: () => getClassifications(single?.id ?? 0),
    enabled: single !== undefined,
  });

  const groups = useMemo(
    () =>
      groupReasons(
        (reasons.data ?? []).filter((r) => matchesSearch(r, search)),
        single?.category ?? null,
      ),
    [reasons.data, search, single?.category],
  );
  const chosen = reasons.data?.find((r) => r.id === selected) ?? null;

  async function save() {
    if (selected === null || !chosen) return;
    await classify.mutateAsync({ eventIds: events.map((e) => e.id), reason: selected, comment });
    onSaved?.(chosen.name);
    onClose();
  }

  const reasonButton = (id: number, label: string) => (
    <button
      key={id}
      type="button"
      aria-pressed={selected === id}
      onClick={() => setSelected(id)}
      className={`min-h-14 rounded-lg border-2 px-4 py-2 text-left text-lg font-semibold ${
        selected === id ? "border-blue-800 bg-blue-700 text-white" : "border-gray-300 bg-white text-gray-900"
      }`}
    >
      {label}
    </button>
  );

  return (
    <div className="fixed inset-0 z-40 flex items-end bg-black/40" role="presentation">
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby="classify-title"
        className="max-h-[90vh] w-full overflow-y-auto rounded-t-2xl bg-gray-50 p-5 shadow-2xl"
      >
        <header className="mb-4 flex items-start justify-between gap-4">
          <div>
            <h2 id="classify-title" className="text-2xl font-bold">
              {single
                ? t("classify.title", { machine: single.machine.name })
                : t("classify.bulkTitle", { count: events.length })}
            </h2>
            {single && (
              <p className="text-lg text-gray-700">
                {t("classify.details", {
                  category: t(CATEGORY_KEY[single.category] ?? "category.breakdown"),
                  duration: formatDuration(single.duration_seconds),
                  time: formatDateTime(single.started_at, zone),
                })}
                {single.alarm_code && ` · ${t("classify.alarm", { code: single.alarm_code })}`}
              </p>
            )}
          </div>
          <button type="button" onClick={onClose} aria-label={t("classify.cancel")} className="p-2">
            <X aria-hidden className="h-8 w-8" />
          </button>
        </header>

        {single && (suggestions.data?.length ?? 0) > 0 && (
          <section className="mb-4">
            <h3 className="mb-2 text-lg font-semibold text-gray-700">{t("classify.suggested")}</h3>
            <div className="grid grid-cols-2 gap-2 md:grid-cols-3">
              {suggestions.data?.map((r) => reasonButton(r.id, r.name))}
            </div>
          </section>
        )}

        <section className="mb-4">
          <h3 className="mb-2 text-lg font-semibold text-gray-700">{t("classify.allReasons")}</h3>
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t("classify.search")}
            aria-label={t("classify.search")}
            className="mb-3 w-full rounded-lg border border-gray-300 px-4 py-3 text-xl"
          />
          {groups.length === 0 && <p className="text-lg text-gray-600">{t("classify.noMatch")}</p>}
          {groups.map((group) => (
            <div key={group.category} className="mb-3" data-testid={`reason-group-${group.category}`}>
              <p className="mb-1 text-base font-semibold uppercase text-gray-600">
                {t(`reasonCategory.${group.category}` as MessageKey)}
              </p>
              <div className="grid grid-cols-2 gap-2 md:grid-cols-3">
                {group.reasons.map((r) => reasonButton(r.id, `${r.name} (${r.code})`))}
              </div>
            </div>
          ))}
        </section>

        <label className="mb-4 flex flex-col gap-1 text-lg">
          {t("classify.comment")}
          <textarea
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            rows={2}
            className="rounded-lg border border-gray-300 px-3 py-2 text-lg"
          />
        </label>

        {classify.isError && (
          <p role="alert" className="mb-3 text-lg text-red-700">
            {t("classify.failed")}
          </p>
        )}
        <div className="flex gap-3">
          <button
            type="button"
            disabled={selected === null || classify.isPending}
            onClick={() => void save()}
            className="min-h-16 flex-1 rounded-lg bg-green-700 px-6 text-2xl font-bold text-white disabled:opacity-50"
          >
            {classify.isPending ? t("classify.saving") : t("classify.save")}
          </button>
          <button
            type="button"
            onClick={onClose}
            className="min-h-16 rounded-lg border-2 border-gray-400 px-6 text-xl"
          >
            {t("classify.cancel")}
          </button>
        </div>

        {single && (
          <section className="mt-5">
            <h3 className="mb-2 text-lg font-semibold text-gray-700">{t("classify.history")}</h3>
            {history.data?.length ? (
              <ul className="flex flex-col gap-1 text-base text-gray-800">
                {history.data.map((h) => (
                  <li key={h.id}>
                    {t("classify.historyItem", {
                      reason: h.reason.name,
                      who: h.created_by ?? "—",
                      time: formatDateTime(h.created_at, zone),
                    })}
                    {h.comment && ` — “${h.comment}”`}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-base text-gray-600">{t("classify.noHistory")}</p>
            )}
          </section>
        )}
      </section>
    </div>
  );
}
