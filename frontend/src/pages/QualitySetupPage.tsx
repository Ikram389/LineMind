import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { useParams } from "react-router";

import { ApiError } from "../api/client.ts";
import { listLineMachines } from "../api/downtime.ts";
import {
  createDefectType,
  createStation,
  type DefectTypeInput,
  deleteDefectType,
  deleteStation,
  listDefectTypes,
  listStations,
  setDefectTypeActive,
  setStationActive,
  type StationInput,
  updateDefectType,
  updateStation,
} from "../api/quality.ts";
import { type DefectType, type InspectionStation, SEVERITIES, type Severity } from "../api/qualityTypes.ts";
import { queryKeys } from "../api/queryKeys.ts";
import { LineNav } from "../components/LineNav.tsx";
import { Panel } from "../components/Panel.tsx";
import type { MessageKey } from "../i18n/en.ts";
import { t } from "../i18n/t.ts";
import { usePermissions } from "../lib/permissions.ts";
import { useLineContext } from "./useLineContext.ts";

const field = "rounded-lg border border-gray-300 px-3 py-2 text-lg";
const button = "min-h-11 rounded border border-gray-400 px-3";

function errorText(error: unknown): string {
  if (error instanceof ApiError && error.body && typeof error.body === "object") {
    return Object.values(error.body as Record<string, unknown>).flat().join(" ");
  }
  return String(error);
}

function ActionButtons({
  active,
  inUse,
  onEdit,
  onActive,
  onDelete,
}: {
  active: boolean;
  inUse: boolean;
  onEdit: () => void;
  onActive: (active: boolean) => void;
  onDelete: () => void;
}) {
  return (
    <div className="flex flex-wrap gap-2">
      <button type="button" onClick={onEdit} className={button}>
        {t("qsetup.edit")}
      </button>
      <button type="button" onClick={() => onActive(!active)} className={button}>
        {active ? t("qsetup.archive") : t("qsetup.restore")}
      </button>
      {inUse ? (
        <span className="self-center text-sm text-gray-500">{t("qsetup.inUse")}</span>
      ) : (
        <button type="button" onClick={onDelete} className={`${button} border-red-400 text-red-800`}>
          {t("qsetup.delete")}
        </button>
      )}
    </div>
  );
}

// --- Defect types ------------------------------------------------------------------------

const EMPTY_TYPE: DefectTypeInput = { code: "", name: "", description: "", severity: "major" };

function DefectTypeForm({
  initial,
  busy,
  onSubmit,
  onCancel,
}: {
  initial: DefectTypeInput;
  busy: boolean;
  onSubmit: (input: DefectTypeInput) => void;
  onCancel: () => void;
}) {
  const [value, setValue] = useState(initial);
  function submit(event: FormEvent) {
    event.preventDefault();
    onSubmit(value);
  }
  return (
    <form onSubmit={submit} className="flex flex-wrap items-end gap-3">
      <label className="flex flex-col text-lg">
        {t("qsetup.code")}
        <input required value={value.code} onChange={(e) => setValue({ ...value, code: e.target.value })} className={field} />
      </label>
      <label className="flex flex-col text-lg">
        {t("qsetup.name")}
        <input required value={value.name} onChange={(e) => setValue({ ...value, name: e.target.value })} className={field} />
      </label>
      <label className="flex flex-col text-lg">
        {t("qsetup.description")}
        <input value={value.description} onChange={(e) => setValue({ ...value, description: e.target.value })} className={field} />
      </label>
      <label className="flex flex-col text-lg">
        {t("qsetup.severity")}
        <select
          value={value.severity}
          onChange={(e) => setValue({ ...value, severity: e.target.value as Severity })}
          className={field}
        >
          {SEVERITIES.map((s) => (
            <option key={s} value={s}>
              {t(`severity.${s}` as MessageKey)}
            </option>
          ))}
        </select>
      </label>
      <button type="submit" disabled={busy} className="min-h-12 rounded-lg bg-blue-700 px-5 text-lg font-semibold text-white">
        {t("qsetup.save")}
      </button>
      <button type="button" onClick={onCancel} className="min-h-12 rounded-lg border border-gray-400 px-5 text-lg">
        {t("qsetup.cancel")}
      </button>
    </form>
  );
}

function DefectTypesSection({ showArchived }: { showArchived: boolean }) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState<number | "new" | null>(null);
  const types = useQuery({ queryKey: queryKeys.defectTypes(true), queryFn: () => listDefectTypes(true) });
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["defectTypes"] });
  const save = useMutation({
    mutationFn: ({ id, input }: { id: number | null; input: DefectTypeInput }) =>
      id === null ? createDefectType(input) : updateDefectType(id, input),
    onSuccess: () => {
      setEditing(null);
      refresh();
    },
  });
  const act = useMutation({
    mutationFn: ({ type, action }: { type: DefectType; action: "archive" | "restore" | "delete" }) =>
      action === "delete" ? deleteDefectType(type.id) : setDefectTypeActive(type.id, action === "restore"),
    onSuccess: refresh,
  });
  const failure = save.error ?? act.error;
  const visible = (types.data ?? []).filter((d) => showArchived || d.is_active);

  return (
    <Panel title={t("qsetup.types")} isLoading={types.isLoading} isError={types.isError}>
      {editing === "new" ? (
        <div className="mb-4 rounded-lg border border-gray-300 p-3">
          <DefectTypeForm
            initial={EMPTY_TYPE}
            busy={save.isPending}
            onCancel={() => setEditing(null)}
            onSubmit={(input) => save.mutate({ id: null, input })}
          />
        </div>
      ) : (
        <button
          type="button"
          onClick={() => setEditing("new")}
          className="mb-4 min-h-12 rounded-lg bg-green-700 px-5 text-lg font-semibold text-white"
        >
          + {t("qsetup.newType")}
        </button>
      )}
      {failure && (
        <p role="alert" className="mb-3 text-lg text-red-700">
          {t("qsetup.failed", { message: errorText(failure) })}
        </p>
      )}
      <table className="w-full text-left text-lg">
        <thead className="border-b-2 border-gray-300">
          <tr>
            <th className="p-2">{t("qsetup.code")}</th>
            <th className="p-2">{t("qsetup.name")}</th>
            <th className="p-2">{t("qsetup.severity")}</th>
            <th className="p-2">{t("qsetup.status")}</th>
            <th className="p-2" />
          </tr>
        </thead>
        <tbody>
          {visible.map((type) =>
            editing === type.id ? (
              <tr key={type.id}>
                <td colSpan={5} className="p-2">
                  <DefectTypeForm
                    initial={{ code: type.code, name: type.name, description: type.description, severity: type.severity }}
                    busy={save.isPending}
                    onCancel={() => setEditing(null)}
                    onSubmit={(input) => save.mutate({ id: type.id, input })}
                  />
                </td>
              </tr>
            ) : (
              <tr key={type.id} className="border-b border-gray-100" data-testid={`defect-type-${type.code}`}>
                <td className="p-2 font-mono">{type.code}</td>
                <td className="p-2">{type.name}</td>
                <td className="p-2">{t(`severity.${type.severity}` as MessageKey)}</td>
                <td className="p-2">{type.is_active ? t("qsetup.active") : t("qsetup.archived")}</td>
                <td className="p-2">
                  <ActionButtons
                    active={type.is_active}
                    inUse={type.in_use}
                    onEdit={() => setEditing(type.id)}
                    onActive={(active) => act.mutate({ type, action: active ? "restore" : "archive" })}
                    onDelete={() => act.mutate({ type, action: "delete" })}
                  />
                </td>
              </tr>
            ),
          )}
        </tbody>
      </table>
    </Panel>
  );
}


// --- Stations ----------------------------------------------------------------------------

interface StationFormValue {
  machine: number | null;
  name: string;
  defect_types: number[];
  source: "simulator" | "vision";
}

function StationForm({
  initial,
  lineId,
  types,
  busy,
  onSubmit,
  onCancel,
}: {
  initial: StationFormValue;
  lineId: number;
  types: DefectType[];
  busy: boolean;
  onSubmit: (input: StationInput) => void;
  onCancel: () => void;
}) {
  const [value, setValue] = useState(initial);
  const machines = useQuery({ queryKey: ["lineMachines", lineId], queryFn: () => listLineMachines(lineId) });
  function submit(event: FormEvent) {
    event.preventDefault();
    if (value.machine === null) return;
    onSubmit({ line: lineId, machine: value.machine, name: value.name, defect_types: value.defect_types, source: value.source });
  }
  const toggle = (id: number) =>
    setValue({
      ...value,
      defect_types: value.defect_types.includes(id)
        ? value.defect_types.filter((x) => x !== id)
        : [...value.defect_types, id],
    });
  return (
    <form onSubmit={submit} className="flex flex-col gap-3">
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col text-lg">
          {t("qsetup.name")}
          <input required value={value.name} onChange={(e) => setValue({ ...value, name: e.target.value })} className={field} />
        </label>
        <label className="flex flex-col text-lg">
          {t("qsetup.machine")}
          <select
            required
            value={value.machine ?? ""}
            onChange={(e) => setValue({ ...value, machine: e.target.value ? Number(e.target.value) : null })}
            className={field}
          >
            <option value="" />
            {(machines.data ?? []).map((m) => (
              <option key={m.id} value={m.id}>
                {m.external_id} {m.name}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col text-lg">
          {t("qsetup.source")}
          <select
            value={value.source}
            onChange={(e) => setValue({ ...value, source: e.target.value as StationFormValue["source"] })}
            className={field}
          >
            <option value="simulator">{t("qsetup.sourceSimulator")}</option>
            <option value="vision">{t("qsetup.sourceVision")}</option>
          </select>
        </label>
      </div>
      <fieldset className="flex flex-wrap gap-3">
        <legend className="text-lg">{t("qsetup.checks")}</legend>
        {types
          .filter((d) => d.is_active)
          .map((d) => (
            <label key={d.id} className="flex items-center gap-2 text-lg">
              <input type="checkbox" checked={value.defect_types.includes(d.id)} onChange={() => toggle(d.id)} className="h-6 w-6" />
              {d.code} · {d.name}
            </label>
          ))}
      </fieldset>
      <div className="flex gap-3">
        <button type="submit" disabled={busy} className="min-h-12 rounded-lg bg-blue-700 px-5 text-lg font-semibold text-white">
          {t("qsetup.save")}
        </button>
        <button type="button" onClick={onCancel} className="min-h-12 rounded-lg border border-gray-400 px-5 text-lg">
          {t("qsetup.cancel")}
        </button>
      </div>
    </form>
  );
}

function StationsSection({ lineId, showArchived }: { lineId: number; showArchived: boolean }) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState<number | "new" | null>(null);
  const stations = useQuery({ queryKey: queryKeys.stations(lineId, true), queryFn: () => listStations(lineId, true) });
  const types = useQuery({ queryKey: queryKeys.defectTypes(true), queryFn: () => listDefectTypes(true) });
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["stations"] });
    void queryClient.invalidateQueries({ queryKey: queryKeys.quality }); // results are re-mapped
  };
  const save = useMutation({
    mutationFn: ({ id, input }: { id: number | null; input: StationInput }) =>
      id === null ? createStation(input) : updateStation(id, input),
    onSuccess: () => {
      setEditing(null);
      refresh();
    },
  });
  const act = useMutation({
    mutationFn: ({ station, action }: { station: InspectionStation; action: "archive" | "restore" | "delete" }) =>
      action === "delete" ? deleteStation(station.id) : setStationActive(station.id, action === "restore"),
    onSuccess: refresh,
  });
  const failure = save.error ?? act.error;
  const allTypes = types.data ?? [];
  const codes = (ids: number[]) =>
    allTypes
      .filter((d) => ids.includes(d.id))
      .map((d) => d.code)
      .join(", ");
  const visible = (stations.data ?? []).filter((s) => showArchived || s.is_active);

  return (
    <Panel title={t("qsetup.stations")} isLoading={stations.isLoading} isError={stations.isError}>
      {editing === "new" ? (
        <div className="mb-4 rounded-lg border border-gray-300 p-3">
          <StationForm
            initial={{ machine: null, name: "", defect_types: [], source: "simulator" }}
            lineId={lineId}
            types={allTypes}
            busy={save.isPending}
            onCancel={() => setEditing(null)}
            onSubmit={(input) => save.mutate({ id: null, input })}
          />
        </div>
      ) : (
        <button
          type="button"
          onClick={() => setEditing("new")}
          className="mb-4 min-h-12 rounded-lg bg-green-700 px-5 text-lg font-semibold text-white"
        >
          + {t("qsetup.newStation")}
        </button>
      )}
      {failure && (
        <p role="alert" className="mb-3 text-lg text-red-700">
          {t("qsetup.failed", { message: errorText(failure) })}
        </p>
      )}
      <table className="w-full text-left text-lg">
        <thead className="border-b-2 border-gray-300">
          <tr>
            <th className="p-2">{t("qsetup.name")}</th>
            <th className="p-2">{t("qsetup.machine")}</th>
            <th className="p-2">{t("qsetup.checks")}</th>
            <th className="p-2">{t("qsetup.status")}</th>
            <th className="p-2" />
          </tr>
        </thead>
        <tbody>
          {visible.map((station) =>
            editing === station.id ? (
              <tr key={station.id}>
                <td colSpan={5} className="p-2">
                  <StationForm
                    initial={station}
                    lineId={lineId}
                    types={allTypes}
                    busy={save.isPending}
                    onCancel={() => setEditing(null)}
                    onSubmit={(input) => save.mutate({ id: station.id, input })}
                  />
                </td>
              </tr>
            ) : (
              <tr key={station.id} className="border-b border-gray-100" data-testid={`station-${station.id}`}>
                <td className="p-2">{station.name}</td>
                <td className="p-2">{station.machine_name}</td>
                <td className="p-2 font-mono">{codes(station.defect_types)}</td>
                <td className="p-2">{station.is_active ? t("qsetup.active") : t("qsetup.archived")}</td>
                <td className="p-2">
                  <ActionButtons
                    active={station.is_active}
                    inUse={station.in_use}
                    onEdit={() => setEditing(station.id)}
                    onActive={(active) => act.mutate({ station, action: active ? "restore" : "archive" })}
                    onDelete={() => act.mutate({ station, action: "delete" })}
                  />
                </td>
              </tr>
            ),
          )}
        </tbody>
      </table>
    </Panel>
  );
}

/** Defect types (organization-wide) and this line's inspection stations, for managers. */
export function QualitySetupPage() {
  const lineId = Number(useParams().lineId);
  const { line, shift } = useLineContext(lineId);
  const { canManageQuality } = usePermissions();
  const [showArchived, setShowArchived] = useState(false);

  if (!canManageQuality) {
    return (
      <main className="p-6">
        <p className="text-xl">{t("qsetup.forbidden")}</p>
      </main>
    );
  }
  return (
    <main className="flex min-h-screen flex-col gap-4 bg-gray-100 p-4">
      <h1 className="text-3xl font-bold">
        {t("qsetup.title")} — {line.data?.name}
      </h1>
      <LineNav lineId={lineId} shift={shift.data} />
      <label className="flex items-center gap-2 text-lg">
        <input type="checkbox" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} className="h-6 w-6" />
        {t("qsetup.showArchived")}
      </label>
      <DefectTypesSection showArchived={showArchived} />
      <StationsSection lineId={lineId} showArchived={showArchived} />
    </main>
  );
}
