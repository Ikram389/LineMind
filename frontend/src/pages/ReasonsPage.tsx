import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { useParams } from "react-router";

import { REASON_CATEGORIES, type Reason, type ReasonCategory } from "../api/analysisTypes.ts";
import { ApiError } from "../api/client.ts";
import {
  archiveReason,
  createReason,
  deleteReason,
  listReasons,
  type ReasonInput,
  restoreReason,
  updateReason,
} from "../api/downtime.ts";
import { LineNav } from "../components/LineNav.tsx";
import { Panel } from "../components/Panel.tsx";
import type { MessageKey } from "../i18n/en.ts";
import { t } from "../i18n/t.ts";
import { usePermissions } from "../lib/permissions.ts";
import { useLineContext } from "./useLineContext.ts";

const EMPTY: ReasonInput = { code: "", name: "", category: "mechanical", is_changeover: false };
const field = "rounded-lg border border-gray-300 px-3 py-2 text-lg";

function errorText(error: unknown): string {
  if (error instanceof ApiError && error.body && typeof error.body === "object") {
    return Object.values(error.body as Record<string, unknown>).flat().join(" ");
  }
  return String(error);
}

function ReasonForm({
  initial,
  onSubmit,
  onCancel,
  busy,
}: {
  initial: ReasonInput;
  onSubmit: (input: ReasonInput) => void;
  onCancel?: () => void;
  busy: boolean;
}) {
  const [value, setValue] = useState(initial);
  function submit(event: FormEvent) {
    event.preventDefault();
    onSubmit(value);
  }
  return (
    <form onSubmit={submit} className="flex flex-wrap items-end gap-3">
      <label className="flex flex-col text-lg">
        {t("reasons.code")}
        <input required value={value.code} onChange={(e) => setValue({ ...value, code: e.target.value })} className={field} />
      </label>
      <label className="flex flex-col text-lg">
        {t("reasons.name")}
        <input required value={value.name} onChange={(e) => setValue({ ...value, name: e.target.value })} className={field} />
      </label>
      <label className="flex flex-col text-lg">
        {t("reasons.category")}
        <select
          value={value.category}
          onChange={(e) => setValue({ ...value, category: e.target.value as ReasonCategory })}
          className={field}
        >
          {REASON_CATEGORIES.map((c) => (
            <option key={c} value={c}>
              {t(`reasonCategory.${c}` as MessageKey)}
            </option>
          ))}
        </select>
      </label>
      <label className="flex items-center gap-2 text-lg">
        <input
          type="checkbox"
          checked={value.is_changeover}
          onChange={(e) => setValue({ ...value, is_changeover: e.target.checked })}
          className="h-6 w-6"
        />
        {t("reasons.changeover")}
      </label>
      <button type="submit" disabled={busy} className="min-h-12 rounded-lg bg-blue-700 px-5 text-lg font-semibold text-white">
        {t("reasons.save")}
      </button>
      {onCancel && (
        <button type="button" onClick={onCancel} className="min-h-12 rounded-lg border border-gray-400 px-5 text-lg">
          {t("reasons.cancel")}
        </button>
      )}
    </form>
  );
}

export function ReasonsPage() {
  const lineId = Number(useParams().lineId);
  const { factory, shift } = useLineContext(lineId);
  const { canManageReasons } = usePermissions();
  const queryClient = useQueryClient();
  const [showArchived, setShowArchived] = useState(false);
  const [editing, setEditing] = useState<number | null>(null);
  const [creating, setCreating] = useState(false);
  const factoryId = factory.data?.id ?? 0;

  const reasons = useQuery({
    queryKey: ["reasons", factoryId, true],
    queryFn: () => listReasons(factoryId, true),
    enabled: factory.isSuccess,
  });
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["reasons"] });
  const save = useMutation({
    mutationFn: ({ id, input }: { id: number | null; input: ReasonInput }) => {
      if (!factory.data) throw new Error("The factory is not loaded yet.");
      return id === null ? createReason(factory.data.id, input) : updateReason(id, input);
    },
    onSuccess: () => {
      setEditing(null);
      setCreating(false);
      refresh();
    },
  });
  const act = useMutation({
    mutationFn: ({ reason, action }: { reason: Reason; action: "archive" | "restore" | "delete" }) =>
      action === "archive" ? archiveReason(reason.id) : action === "restore" ? restoreReason(reason.id) : deleteReason(reason.id),
    onSuccess: refresh,
  });

  if (!canManageReasons) {
    return (
      <main className="p-6">
        <p className="text-xl">{t("reasons.forbidden")}</p>
      </main>
    );
  }

  const visible = (reasons.data ?? []).filter((r) => showArchived || r.is_active);
  const failure = save.error ?? act.error;

  return (
    <main className="flex min-h-screen flex-col gap-4 bg-gray-100 p-4">
      <h1 className="text-3xl font-bold">
        {t("reasons.title")} — {factory.data?.name}
      </h1>
      <LineNav lineId={lineId} shift={shift.data} />
      <Panel
        isLoading={!reasons.isSuccess && !reasons.isError && !factory.isError}
        isError={factory.isError || reasons.isError}
      >
        <div className="mb-4 flex flex-wrap items-center gap-4">
          {!creating && (
            <button type="button" onClick={() => setCreating(true)} className="min-h-12 rounded-lg bg-green-700 px-5 text-lg font-semibold text-white">
              + {t("reasons.new")}
            </button>
          )}
          <label className="flex items-center gap-2 text-lg">
            <input type="checkbox" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} className="h-6 w-6" />
            {t("reasons.showArchived")}
          </label>
        </div>
        {creating && (
          <div className="mb-4 rounded-lg border border-gray-300 p-3">
            <ReasonForm initial={EMPTY} busy={save.isPending} onCancel={() => setCreating(false)} onSubmit={(input) => save.mutate({ id: null, input })} />
          </div>
        )}
        {failure && (
          <p role="alert" className="mb-3 text-lg text-red-700">
            {t("reasons.failed", { message: errorText(failure) })}
          </p>
        )}
        <table className="w-full text-left text-lg">
          <thead className="border-b-2 border-gray-300">
            <tr>
              <th className="p-2">{t("reasons.code")}</th>
              <th className="p-2">{t("reasons.name")}</th>
              <th className="p-2">{t("reasons.category")}</th>
              <th className="p-2">{t("reasons.changeover")}</th>
              <th className="p-2">{t("reasons.status")}</th>
              <th className="p-2" />
            </tr>
          </thead>
          <tbody>
            {visible.map((reason) =>
              editing === reason.id ? (
                <tr key={reason.id}>
                  <td colSpan={6} className="p-2">
                    <ReasonForm
                      initial={{ code: reason.code, name: reason.name, category: reason.category, is_changeover: reason.is_changeover }}
                      busy={save.isPending}
                      onCancel={() => setEditing(null)}
                      onSubmit={(input) => save.mutate({ id: reason.id, input })}
                    />
                  </td>
                </tr>
              ) : (
                <tr key={reason.id} className="border-b border-gray-100" data-testid={`reason-${reason.code}`}>
                  <td className="p-2 font-mono">{reason.code}</td>
                  <td className="p-2">{reason.name}</td>
                  <td className="p-2">{t(`reasonCategory.${reason.category}` as MessageKey)}</td>
                  <td className="p-2">{reason.is_changeover ? "✓" : ""}</td>
                  <td className="p-2">{reason.is_active ? t("reasons.active") : t("reasons.archived")}</td>
                  <td className="flex flex-wrap gap-2 p-2">
                    <button type="button" onClick={() => setEditing(reason.id)} className="min-h-11 rounded border border-gray-400 px-3">
                      {t("reasons.edit")}
                    </button>
                    {reason.is_active ? (
                      <button type="button" onClick={() => act.mutate({ reason, action: "archive" })} className="min-h-11 rounded border border-gray-400 px-3">
                        {t("reasons.archive")}
                      </button>
                    ) : (
                      <button type="button" onClick={() => act.mutate({ reason, action: "restore" })} className="min-h-11 rounded border border-gray-400 px-3">
                        {t("reasons.restore")}
                      </button>
                    )}
                    {reason.in_use ? (
                      <span className="self-center text-sm text-gray-500" title={t("reasons.inUse")}>
                        {t("reasons.inUse")}
                      </span>
                    ) : (
                      <button type="button" onClick={() => act.mutate({ reason, action: "delete" })} className="min-h-11 rounded border border-red-400 px-3 text-red-800">
                        {t("reasons.delete")}
                      </button>
                    )}
                  </td>
                </tr>
              ),
            )}
          </tbody>
        </table>
      </Panel>
    </main>
  );
}
