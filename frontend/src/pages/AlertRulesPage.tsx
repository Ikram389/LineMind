import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";

import {
  createAlertRule,
  deleteAlertRule,
  getRuleTypes,
  listAlertRules,
  updateAlertRule,
} from "../api/alerts.ts";
import {
  ALERT_SEVERITIES,
  type AlertRule,
  type AlertRuleInput,
  type AlertSeverity,
  type RuleType,
  type RuleTypeInfo,
} from "../api/alertTypes.ts";
import { ApiError } from "../api/client.ts";
import { listLineMachines } from "../api/downtime.ts";
import { listLines } from "../api/endpoints.ts";
import { queryKeys } from "../api/queryKeys.ts";
import type { Role } from "../api/types.ts";
import { useAuth } from "../auth/context.ts";
import { Panel } from "../components/Panel.tsx";
import type { MessageKey } from "../i18n/en.ts";
import { t } from "../i18n/t.ts";
import { ruleTypeLabel, severityLabel } from "../lib/alertText.ts";
import { usePermissions } from "../lib/permissions.ts";
import { paramError } from "../lib/ruleForm.ts";

const ROLES: Role[] = [
  "machine_operator",
  "production_supervisor",
  "factory_manager",
  "maintenance_technician",
  "quality_inspector",
  "platform_admin",
  "analyst",
];
const field = "rounded-lg border border-gray-300 bg-white px-3 py-2 text-lg";

type ParamValues = Record<string, string>;

function errorText(error: unknown): string {
  if (error instanceof ApiError && error.body && typeof error.body === "object") {
    return JSON.stringify(error.body).replace(/[{}[\]"]/g, " ").replace(/\s+/g, " ").trim();
  }
  return String(error);
}

const roleNames = (roles: Role[]) => roles.map((r) => t(`roleName.${r}` as MessageKey)).join(", ");

function toParams(info: RuleTypeInfo, values: ParamValues): Record<string, string | number | null> {
  const result: Record<string, string | number | null> = {};
  for (const param of info.parameters) {
    const raw = values[param.name] ?? "";
    if (raw.trim() === "") continue; // the backend fills in the default
    result[param.name] = param.choices ? raw : Number(raw);
  }
  return result;
}

interface RuleFormProps {
  factoryId: number;
  types: RuleTypeInfo[];
  initial: AlertRule | null;
  busy: boolean;
  onSubmit: (input: AlertRuleInput) => void;
  onCancel: () => void;
}

function RuleForm({ factoryId, types, initial, busy, onSubmit, onCancel }: RuleFormProps) {
  const [ruleType, setRuleType] = useState<RuleType>(initial?.rule_type ?? "long_stop");
  const [name, setName] = useState(initial?.name ?? "");
  const [severity, setSeverity] = useState<AlertSeverity>(initial?.severity ?? "warning");
  const [line, setLine] = useState<number | null>(initial?.line ?? null);
  const [machine, setMachine] = useState<number | null>(initial?.machine ?? null);
  const [params, setParams] = useState<ParamValues>(
    Object.fromEntries(Object.entries(initial?.parameters ?? {}).map(([k, v]) => [k, v === null ? "" : String(v)])),
  );
  const [recipients, setRecipients] = useState<Role[]>(initial?.recipient_roles ?? ["production_supervisor"]);
  const [cooldown, setCooldown] = useState(String(initial?.cooldown_minutes ?? 30));
  const [escalate, setEscalate] = useState(
    initial ? (initial.escalate_after_minutes === null ? "" : String(initial.escalate_after_minutes)) : "15",
  );
  const [escalationRoles, setEscalationRoles] = useState<Role[]>(initial?.escalation_roles ?? ["factory_manager"]);
  const [outsideShifts, setOutsideShifts] = useState(initial?.active_outside_shifts ?? false);
  const [errors, setErrors] = useState<Record<string, string>>({});

  const lines = useQuery({ queryKey: queryKeys.lines, queryFn: listLines });
  const machines = useQuery({
    queryKey: ["lineMachines", line],
    queryFn: () => listLineMachines(line ?? 0),
    enabled: line !== null,
  });
  const info = types.find((x) => x.type === ruleType);

  const toggle = (list: Role[], role: Role) => (list.includes(role) ? list.filter((r) => r !== role) : [...list, role]);

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!info) return;
    const found: Record<string, string> = {};
    for (const param of info.parameters) {
      const message = paramError(param, params[param.name] ?? "");
      if (message) found[param.name] = message;
    }
    if (recipients.length === 0) found.recipients = "Choose at least one role.";
    if (escalate.trim() !== "" && severity !== "info" && escalationRoles.length === 0) {
      found.escalation = "Choose who to tell when the alert is not acknowledged.";
    }
    setErrors(found);
    if (Object.keys(found).length > 0) return;
    onSubmit({
      factory: factoryId,
      line,
      machine: info.machine_scoped ? machine : null,
      name,
      rule_type: ruleType,
      parameters: toParams(info, params),
      severity,
      is_enabled: initial?.is_enabled ?? true,
      recipient_roles: recipients,
      cooldown_minutes: Number(cooldown) || 0,
      escalate_after_minutes: escalate.trim() === "" ? null : Number(escalate),
      escalation_roles: escalationRoles,
      active_outside_shifts: outsideShifts,
    });
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-4" aria-label={t("rules.new")}>
      <div className="flex flex-wrap gap-3">
        <label className="flex flex-col text-lg">
          {t("rules.type")}
          <select
            value={ruleType}
            disabled={initial !== null}
            onChange={(e) => {
              setRuleType(e.target.value as RuleType);
              setParams({});
              setErrors({});
            }}
            className={field}
          >
            {types.map((x) => (
              <option key={x.type} value={x.type}>
                {ruleTypeLabel(x.type)}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col text-lg">
          {t("rules.name")}
          <input value={name} onChange={(e) => setName(e.target.value)} className={field} />
        </label>
      </div>
      <p className="rounded-lg bg-blue-50 p-3 text-lg text-blue-900" data-testid="rule-help">
        {t(`rules.help.${ruleType}` as MessageKey)}
      </p>
      <div className="flex flex-wrap gap-3">
        {info?.parameters.map((param) => {
          const errorId = `param-error-${param.name}`;
          return (
            <div key={param.name} className="flex flex-col">
              <label className="flex flex-col text-lg">
                {t(`param.${param.name}` as MessageKey)}
                {param.choices ? (
                  <select
                    value={params[param.name] ?? String(param.default ?? "")}
                    onChange={(e) => setParams({ ...params, [param.name]: e.target.value })}
                    className={field}
                  >
                    {param.choices.map((choice) => (
                      <option key={choice} value={choice}>
                        {t(`param.${param.name}.${choice}` as MessageKey)}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    inputMode="decimal"
                    value={params[param.name] ?? ""}
                    placeholder={
                      param.default === null ? t("rules.factoryDefault") : t("rules.default", { value: param.default })
                    }
                    onChange={(e) => setParams({ ...params, [param.name]: e.target.value })}
                    aria-invalid={Boolean(errors[param.name])}
                    aria-describedby={errors[param.name] ? errorId : undefined}
                    className={field}
                  />
                )}
              </label>
              {errors[param.name] && (
                <span id={errorId} role="alert" className="text-base text-red-700">
                  {errors[param.name]}
                </span>
              )}
            </div>
          );
        })}
      </div>
      <fieldset className="flex flex-wrap gap-4">
        <legend className="text-lg font-semibold">{t("rules.severity")}</legend>
        {ALERT_SEVERITIES.map((s) => (
          <label key={s} className="flex items-center gap-2 text-lg">
            <input type="radio" name="severity" checked={severity === s} onChange={() => setSeverity(s)} className="h-5 w-5" />
            {severityLabel(s)}
          </label>
        ))}
      </fieldset>
      <div className="flex flex-wrap gap-3">
        <label className="flex flex-col text-lg">
          {t("rules.line")}
          <select
            value={line ?? ""}
            onChange={(e) => {
              setLine(e.target.value ? Number(e.target.value) : null);
              setMachine(null);
            }}
            className={field}
          >
            <option value="">{t("rules.allLines")}</option>
            {(lines.data ?? [])
              .filter((l) => l.factory === factoryId)
              .map((l) => (
                <option key={l.id} value={l.id}>
                  {l.name}
                </option>
              ))}
          </select>
        </label>
        {info?.machine_scoped && line !== null && (
          <label className="flex flex-col text-lg">
            {t("rules.machine")}
            <select value={machine ?? ""} onChange={(e) => setMachine(e.target.value ? Number(e.target.value) : null)} className={field}>
              <option value="">{t("rules.allMachines")}</option>
              {(machines.data ?? []).map((m) => (
                <option key={m.id} value={m.id}>
                  {m.external_id} {m.name}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>
      <fieldset className="flex flex-wrap gap-4">
        <legend className="text-lg font-semibold">{t("rules.recipients")}</legend>
        {ROLES.map((role) => (
          <label key={role} className="flex items-center gap-2 text-lg">
            <input type="checkbox" checked={recipients.includes(role)} onChange={() => setRecipients(toggle(recipients, role))} className="h-6 w-6" />
            {t(`roleName.${role}` as MessageKey)}
          </label>
        ))}
        {errors.recipients && <span role="alert" className="w-full text-base text-red-700">{errors.recipients}</span>}
      </fieldset>
      <div className="flex flex-wrap gap-3">
        <label className="flex flex-col text-lg">
          {t("rules.cooldown")}
          <input inputMode="numeric" value={cooldown} onChange={(e) => setCooldown(e.target.value)} className={field} />
        </label>
        <label className="flex flex-col text-lg">
          {t("rules.escalate")}
          <input inputMode="numeric" value={escalate} onChange={(e) => setEscalate(e.target.value)} className={field} />
        </label>
      </div>
      {escalate.trim() !== "" && severity !== "info" && (
        <fieldset className="flex flex-wrap gap-4">
          <legend className="text-lg font-semibold">{t("rules.escalateTo")}</legend>
          {ROLES.map((role) => (
            <label key={role} className="flex items-center gap-2 text-lg">
              <input
                type="checkbox"
                checked={escalationRoles.includes(role)}
                onChange={() => setEscalationRoles(toggle(escalationRoles, role))}
                className="h-6 w-6"
              />
              {t(`roleName.${role}` as MessageKey)}
            </label>
          ))}
          {errors.escalation && <span role="alert" className="w-full text-base text-red-700">{errors.escalation}</span>}
        </fieldset>
      )}
      <label className="flex items-center gap-2 text-lg">
        <input type="checkbox" checked={outsideShifts} onChange={(e) => setOutsideShifts(e.target.checked)} className="h-6 w-6" />
        {t("rules.outsideShifts")}
      </label>
      <div className="flex gap-3">
        <button type="submit" disabled={busy} className="min-h-12 rounded-lg bg-blue-700 px-5 text-lg font-semibold text-white">
          {t("rules.save")}
        </button>
        <button type="button" onClick={onCancel} className="min-h-12 rounded-lg border border-gray-400 px-5 text-lg">
          {t("rules.cancel")}
        </button>
      </div>
    </form>
  );
}

/** Factory managers: the alert rules of a factory, on/off, create and edit. */
export function AlertRulesPage() {
  const { user } = useAuth();
  const { canManageAlertRules } = usePermissions();
  const queryClient = useQueryClient();
  const factories = user?.factories ?? [];
  const [factoryId, setFactoryId] = useState<number | null>(factories[0]?.id ?? null);
  const [editing, setEditing] = useState<AlertRule | "new" | null>(null);

  const rules = useQuery({
    queryKey: queryKeys.alertRules(factoryId ?? 0),
    queryFn: () => listAlertRules(factoryId ?? 0),
    enabled: factoryId !== null && canManageAlertRules,
  });
  const types = useQuery({ queryKey: queryKeys.ruleTypes, queryFn: getRuleTypes, enabled: canManageAlertRules });
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["alertRules"] });
  const save = useMutation({
    mutationFn: ({ id, input }: { id: number | null; input: Partial<AlertRuleInput> }) =>
      id === null ? createAlertRule(input as AlertRuleInput) : updateAlertRule(id, input),
    onSuccess: () => {
      setEditing(null);
      refresh();
    },
  });
  const remove = useMutation({ mutationFn: deleteAlertRule, onSuccess: refresh });

  if (!canManageAlertRules) {
    return (
      <main className="p-6">
        <p className="text-xl">{t("rules.forbidden")}</p>
      </main>
    );
  }
  const failure = save.error ?? remove.error;

  return (
    <main className="flex min-h-screen flex-col gap-4 bg-gray-100 p-4">
      <h1 className="text-3xl font-bold">{t("rules.title")}</h1>
      <label className="flex items-center gap-2 text-lg">
        {t("rules.factory")}
        <select value={factoryId ?? ""} onChange={(e) => setFactoryId(Number(e.target.value))} className={field}>
          {factories.map((f) => (
            <option key={f.id} value={f.id}>
              {f.name}
            </option>
          ))}
        </select>
      </label>
      {failure && (
        <p role="alert" className="text-lg text-red-700">
          {t("rules.failed", { message: errorText(failure) })}
        </p>
      )}
      <Panel isLoading={rules.isLoading || types.isLoading} isError={rules.isError || types.isError}>
        {editing !== null && factoryId !== null && types.data ? (
          <RuleForm
            factoryId={factoryId}
            types={types.data}
            initial={editing === "new" ? null : editing}
            busy={save.isPending}
            onCancel={() => setEditing(null)}
            onSubmit={(input) => save.mutate({ id: editing === "new" ? null : editing.id, input })}
          />
        ) : (
          <>
            <button
              type="button"
              onClick={() => setEditing("new")}
              className="mb-4 min-h-12 rounded-lg bg-green-700 px-5 text-lg font-semibold text-white"
            >
              + {t("rules.new")}
            </button>
            <ul className="flex flex-col gap-2">
              {(rules.data ?? []).map((rule) => (
                <li key={rule.id} data-testid={`rule-${rule.id}`} className="flex flex-wrap items-center gap-3 rounded-lg border border-gray-200 p-3">
                  <label className="flex items-center gap-2 text-lg font-semibold">
                    <input
                      type="checkbox"
                      checked={rule.is_enabled}
                      aria-label={t("rules.toggle", { name: rule.name || ruleTypeLabel(rule.rule_type) })}
                      onChange={(e) => save.mutate({ id: rule.id, input: { is_enabled: e.target.checked } })}
                      className="h-6 w-6"
                    />
                    {rule.is_enabled ? t("rules.enabled") : t("rules.disabled")}
                  </label>
                  <span className="text-lg font-semibold">{rule.name || ruleTypeLabel(rule.rule_type)}</span>
                  <span className="text-lg text-gray-700">
                    {t("rules.summary", { severity: severityLabel(rule.severity), recipients: roleNames(rule.recipient_roles) })}
                    {rule.escalate_after_minutes !== null &&
                      rule.severity !== "info" &&
                      t("rules.escalationSummary", { minutes: rule.escalate_after_minutes })}
                  </span>
                  <span className="ml-auto flex gap-2">
                    <button type="button" onClick={() => setEditing(rule)} className="min-h-11 rounded border border-gray-400 px-3">
                      {t("rules.edit")}
                    </button>
                    <button type="button" onClick={() => remove.mutate(rule.id)} className="min-h-11 rounded border border-red-400 px-3 text-red-800">
                      {t("rules.delete")}
                    </button>
                  </span>
                </li>
              ))}
            </ul>
          </>
        )}
      </Panel>
    </main>
  );
}
