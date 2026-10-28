import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { getClassifications, getSuggestedReasons, listReasons } from "../api/downtime.ts";
import { queryKeys } from "../api/queryKeys.ts";
import type { MessageKey } from "../i18n/en.ts";
import { t } from "../i18n/t.ts";
import type { ClassifyTarget } from "../lib/classifyTarget.ts";
import { groupReasons, matchesSearch } from "../lib/reasonOrder.ts";
import { formatDateTime, formatDuration } from "../lib/time.ts";
import { useClassify } from "../lib/useClassify.ts";
import { CATEGORY_KEY } from "./downtime/categories.ts";
import { Button } from "./ui/Button.tsx";
import { buttonClass } from "./ui/buttonClass.ts";
import { EmptyState } from "./ui/Feedback.tsx";
import { Field, controlClass } from "./ui/Field.tsx";
import { Dialog } from "./ui/Overlay.tsx";

interface ClassifyPanelProps {
  events: ClassifyTarget[]; // one stop, or several for bulk classification
  factoryId: number;
  zone: string;
  onClose: () => void;
  onSaved?: (reasonName: string) => void;
}

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
      className={buttonClass(selected === id ? "primary" : "secondary", "tile", "justify-start text-left")}
    >
      {label}
    </button>
  );

  return (
    <Dialog
      size="lg"
      onClose={onClose}
      title={single ? t("classify.title", { machine: single.machine.name }) : t("classify.bulkTitle", { count: events.length })}
      subtitle={
        single && (
          <>
            {t("classify.details", {
              category: t(CATEGORY_KEY[single.category] ?? "category.breakdown"),
              duration: formatDuration(single.duration_seconds),
              time: formatDateTime(single.started_at, zone),
            })}
            {single.alarm_code && ` · ${t("classify.alarm", { code: single.alarm_code })}`}
          </>
        )
      }
      footer={
        <>
          {classify.isError && (
            <p role="alert" className="mr-auto self-center text-body font-semibold text-critical">
              {t("classify.failed")}
            </p>
          )}
          <Button size="lg" onClick={onClose}>
            {t("classify.cancel")}
          </Button>
          <Button size="lg" variant="primary" disabled={selected === null || classify.isPending} onClick={() => void save()}>
            {classify.isPending ? t("classify.saving") : t("classify.save")}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-6">
        {single && (suggestions.data?.length ?? 0) > 0 && (
          <section className="flex flex-col gap-2">
            <h3 className="text-small font-semibold uppercase tracking-wide text-ink-muted">{t("classify.suggested")}</h3>
            <div className="grid grid-cols-2 gap-2 md:grid-cols-3">
              {suggestions.data?.map((r) => reasonButton(r.id, r.name))}
            </div>
          </section>
        )}

        <section className="flex flex-col gap-3">
          <h3 className="text-small font-semibold uppercase tracking-wide text-ink-muted">{t("classify.allReasons")}</h3>
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t("classify.search")}
            aria-label={t("classify.search")}
            className={`${controlClass} w-full`}
          />
          {groups.length === 0 && <EmptyState title={t("classify.noMatch")} />}
          {groups.map((group) => (
            <div key={group.category} className="flex flex-col gap-2" data-testid={`reason-group-${group.category}`}>
              <p className="text-small font-semibold text-ink-muted">
                {t(`reasonCategory.${group.category}` as MessageKey)}
              </p>
              <div className="grid grid-cols-2 gap-2 md:grid-cols-3">
                {group.reasons.map((r) => reasonButton(r.id, `${r.name} (${r.code})`))}
              </div>
            </div>
          ))}
        </section>

        <Field label={t("classify.comment")}>
          {(props) => (
            <textarea
              {...props}
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              rows={2}
              className={`${controlClass} py-2`}
            />
          )}
        </Field>

        {single && (
          <section className="flex flex-col gap-2">
            <h3 className="text-small font-semibold uppercase tracking-wide text-ink-muted">{t("classify.history")}</h3>
            {history.data?.length ? (
              <ul className="flex flex-col gap-1 text-small text-ink">
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
              <p className="text-small text-ink-muted">{t("classify.noHistory")}</p>
            )}
          </section>
        )}
      </div>
    </Dialog>
  );
}
