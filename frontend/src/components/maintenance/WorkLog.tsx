import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";

import { addEntry, listEntries } from "../../api/maintenance.ts";
import type { Part, WorkEntry } from "../../api/maintenanceTypes.ts";
import { queryKeys } from "../../api/queryKeys.ts";
import type { MessageKey } from "../../i18n/en.ts";
import { t } from "../../i18n/t.ts";
import { formatDateTime } from "../../lib/time.ts";

const KINDS: WorkEntry["kind"][] = ["comment", "diagnosis", "repair"];
const field = "rounded-lg border border-gray-300 bg-white px-3 py-2 text-lg";

/** The work log: large controls for a tablet; entries are never edited. */
export function WorkLog({ actionId, zone, canWrite }: { actionId: number; zone: string; canWrite: boolean }) {
  const queryClient = useQueryClient();
  const entries = useQuery({ queryKey: [...queryKeys.maintenanceAction(actionId), "entries"], queryFn: () => listEntries(actionId) });
  const [kind, setKind] = useState<WorkEntry["kind"]>("comment");
  const [text, setText] = useState("");
  const [minutes, setMinutes] = useState("");
  const [parts, setParts] = useState<Part[]>([]);
  const add = useMutation({
    mutationFn: () =>
      addEntry(actionId, {
        kind,
        text,
        time_spent_minutes: Number(minutes) || 0,
        parts: parts.filter((p) => p.name.trim()),
      }),
    onSuccess: () => {
      setText("");
      setMinutes("");
      setParts([]);
      void queryClient.invalidateQueries({ queryKey: queryKeys.maintenanceAction(actionId) });
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    if (text.trim()) add.mutate();
  }

  return (
    <div className="flex flex-col gap-4">
      {canWrite && (
        <form onSubmit={submit} className="flex flex-col gap-3" aria-label={t("maint.log")}>
          <div className="grid grid-cols-3 gap-2" role="group" aria-label={t("maint.log")}>
            {KINDS.map((k) => (
              <button
                key={k}
                type="button"
                aria-pressed={kind === k}
                onClick={() => setKind(k)}
                className={`min-h-14 rounded-xl border-2 text-lg font-semibold ${kind === k ? "border-blue-800 bg-blue-700 text-white" : "border-gray-300"}`}
              >
                {t(`maint.log.kind.${k}` as MessageKey)}
              </button>
            ))}
          </div>
          <label className="flex flex-col text-lg">
            {t("maint.log.text")}
            <textarea value={text} onChange={(e) => setText(e.target.value)} rows={3} className={field} />
          </label>
          <div className="flex flex-wrap items-end gap-3">
            <label className="flex flex-col text-lg">
              {t("maint.log.minutes")}
              <input inputMode="numeric" value={minutes} onChange={(e) => setMinutes(e.target.value)} className={`${field} w-32`} />
            </label>
            {parts.map((part, index) => (
              <div key={index} className="flex items-end gap-2">
                <label className="flex flex-col text-lg">
                  {t("maint.log.part")}
                  <input
                    value={part.name}
                    onChange={(e) => setParts(parts.map((p, i) => (i === index ? { ...p, name: e.target.value } : p)))}
                    className={field}
                  />
                </label>
                <label className="flex flex-col text-lg">
                  {t("maint.log.quantity")}
                  <input
                    inputMode="decimal"
                    value={String(part.quantity)}
                    onChange={(e) => setParts(parts.map((p, i) => (i === index ? { ...p, quantity: Number(e.target.value) || 0 } : p)))}
                    className={`${field} w-24`}
                  />
                </label>
              </div>
            ))}
            <button type="button" onClick={() => setParts([...parts, { name: "", quantity: 1 }])} className="min-h-12 rounded-lg border border-gray-400 px-4 text-lg">
              {t("maint.log.addPart")}
            </button>
          </div>
          <button type="submit" disabled={!text.trim() || add.isPending} className="min-h-14 rounded-xl bg-gray-900 text-xl font-bold text-white disabled:opacity-40">
            {t("maint.log.add")}
          </button>
        </form>
      )}
      {entries.data && entries.data.length === 0 && <p className="text-lg text-gray-600">{t("maint.log.empty")}</p>}
      <ol className="flex flex-col gap-2" data-testid="work-log">
        {(entries.data ?? []).map((entry) => (
          <li key={entry.id} className="rounded-lg border border-gray-200 p-3">
            <p className="text-base text-gray-600">
              {t("maint.log.entry", {
                kind: t(`maint.log.kind.${entry.kind}` as MessageKey),
                who: entry.author.email,
                time: formatDateTime(entry.created_at, zone),
              })}
              {entry.time_spent_minutes > 0 && ` · ${t("maint.log.spent", { minutes: entry.time_spent_minutes })}`}
            </p>
            <p className="text-lg">{entry.text}</p>
            {entry.parts.length > 0 && (
              <p className="text-base text-gray-700">{entry.parts.map((p) => `${p.name} × ${p.quantity}`).join(", ")}</p>
            )}
          </li>
        ))}
      </ol>
    </div>
  );
}
