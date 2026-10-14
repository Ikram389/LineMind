import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CircleAlert, Info, OctagonAlert } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";

import { acknowledgeAlert, resolveAlert } from "../../api/alerts.ts";
import type { Alert, AlertSeverity } from "../../api/alertTypes.ts";
import { ApiError } from "../../api/client.ts";
import { queryKeys } from "../../api/queryKeys.ts";
import { CreateActionButton } from "../maintenance/CreateActionDialog.tsx";
import type { MessageKey } from "../../i18n/en.ts";
import { t } from "../../i18n/t.ts";
import { alertMessage, severityLabel, SEVERITY_STYLE, subjectHref } from "../../lib/alertText.ts";
import { formatDateTime, formatShortDuration, secondsBetween } from "../../lib/time.ts";

const ICONS: Record<AlertSeverity, typeof Info> = { critical: OctagonAlert, warning: CircleAlert, info: Info };

function errorText(error: unknown): string {
  if (error instanceof ApiError && error.body && typeof error.body === "object") {
    return Object.values(error.body as Record<string, unknown>).flat().join(" ");
  }
  return String(error);
}

interface AlertCardProps {
  alert: Alert;
  nowMs: number;
  canResolve: boolean;
  highlighted?: boolean;
  onOpenIncident?: (incidentId: number) => void;
}

/** One alert: severity (colour, icon and text), what, since when, subject link, actions. */
export function AlertCard({ alert, nowMs, canResolve, highlighted, onOpenIncident }: AlertCardProps) {
  const queryClient = useQueryClient();
  const [note, setNote] = useState("");
  const [resolving, setResolving] = useState(false);
  const [resolveNote, setResolveNote] = useState("");
  const zone = alert.factory_timezone;
  const Icon = ICONS[alert.severity];
  const done = () => void queryClient.invalidateQueries({ queryKey: queryKeys.alerts });
  const ack = useMutation({ mutationFn: () => acknowledgeAlert(alert.id, note), onSuccess: done });
  const resolve = useMutation({ mutationFn: () => resolveAlert(alert.id, resolveNote), onSuccess: done });
  const href = subjectHref(alert);
  const failure = ack.error ?? resolve.error;

  return (
    <article
      data-testid={`alert-${alert.id}`}
      className={`rounded-xl border-l-8 p-4 shadow-sm ${SEVERITY_STYLE[alert.severity]} ${
        alert.status === "resolved" ? "opacity-70" : ""
      } ${highlighted ? "ring-4 ring-blue-500" : ""}`}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="flex items-center gap-2 text-lg font-bold uppercase">
            <Icon aria-hidden className="h-6 w-6" />
            {severityLabel(alert.severity)} · {t(`alertStatus.${alert.status}` as MessageKey)}
          </p>
          <h2 className="text-2xl font-bold">{alertMessage(alert.message_key, alert.message_values)}</h2>
          <p className="text-lg">
            {alert.line?.name}
            {alert.machine && ` · ${alert.machine.name}`}
            {" · "}
            {alert.status === "resolved"
              ? alert.resolution === "auto"
                ? t("alerts.resolvedAuto", { time: formatDateTime(alert.resolved_at ?? "", zone) })
                : t("alerts.resolvedBy", {
                    who: alert.resolved_by ?? "",
                    time: formatDateTime(alert.resolved_at ?? "", zone),
                    note: alert.resolution_note,
                  })
              : t("alerts.openFor", { duration: formatShortDuration(secondsBetween(alert.opened_at, nowMs)) })}
            {" · "}
            {t("alerts.since", { time: formatDateTime(alert.condition_since, zone) })}
          </p>
          {alert.acknowledged_by && (
            <p className="text-lg">
              {t("alerts.ackBy", { who: alert.acknowledged_by, time: formatDateTime(alert.acknowledged_at ?? "", zone) })}
              {alert.acknowledge_note && ` — “${alert.acknowledge_note}”`}
            </p>
          )}
          {alert.escalated_at && <p className="text-lg">{t("alerts.escalated", { time: formatDateTime(alert.escalated_at, zone) })}</p>}
        </div>
        {href &&
          (alert.subject.type === "incident" && onOpenIncident && alert.subject.id ? (
            <button
              type="button"
              onClick={() => onOpenIncident(alert.subject.id ?? 0)}
              className="text-lg text-blue-800 underline"
            >
              {t("alerts.openSubject", { what: t("alerts.subject.incident") })}
            </button>
          ) : (
            <Link to={href} className="text-lg text-blue-800 underline">
              {t("alerts.openSubject", { what: t(`alerts.subject.${alert.subject.type}` as MessageKey) })}
            </Link>
          ))}
      </div>

      {alert.machine && (
        <div className="mt-2">
          <CreateActionButton source={{ source: "alert", id: alert.id }} compact />
        </div>
      )}
      {alert.status === "open" && alert.can_acknowledge && (
        <div className="mt-3 flex flex-wrap items-end gap-3">
          <button
            type="button"
            onClick={() => ack.mutate()}
            disabled={ack.isPending}
            className="min-h-14 rounded-xl bg-gray-900 px-6 text-xl font-bold text-white"
          >
            ✓ {t("alerts.acknowledge")}
          </button>
          <label className="flex flex-col text-lg">
            {t("alerts.note")}
            <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={1000} className="rounded-lg border border-gray-400 bg-white px-3 py-2 text-lg" />
          </label>
        </div>
      )}
      {alert.status !== "resolved" && canResolve && (
        <div className="mt-3">
          {resolving ? (
            <div className="flex flex-wrap items-end gap-3">
              <label className="flex flex-col text-lg">
                {t("alerts.resolveNote")}
                <input
                  value={resolveNote}
                  onChange={(e) => setResolveNote(e.target.value)}
                  maxLength={1000}
                  className="rounded-lg border border-gray-400 bg-white px-3 py-2 text-lg"
                />
              </label>
              <button
                type="button"
                disabled={!resolveNote.trim() || resolve.isPending}
                onClick={() => resolve.mutate()}
                className="min-h-12 rounded-lg bg-green-800 px-4 text-lg font-semibold text-white disabled:opacity-40"
              >
                {t("alerts.resolveConfirm")}
              </button>
              <button type="button" onClick={() => setResolving(false)} className="min-h-12 rounded-lg border border-gray-400 px-4 text-lg">
                {t("alerts.cancel")}
              </button>
            </div>
          ) : (
            <button type="button" onClick={() => setResolving(true)} className="min-h-12 rounded-lg border-2 border-gray-500 px-4 text-lg">
              {t("alerts.resolve")}
            </button>
          )}
        </div>
      )}
      {failure && (
        <p role="alert" className="mt-2 text-lg text-red-800">
          {t("alerts.failed", { message: errorText(failure) })}
        </p>
      )}
    </article>
  );
}
