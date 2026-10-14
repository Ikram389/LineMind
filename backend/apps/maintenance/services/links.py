"""Evidence linked to an action, and the pre-filled form for "create action from …".

Links only point at observations (stops, incidents, alerts, defects); nothing they
point at is ever changed. Every link must belong to the action's factory.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from django.db.models import QuerySet

from apps.accounts.models import User
from apps.downtime.models import (
    DowntimeCategory,
    DowntimeEvent,
    DowntimeReason,
    LineStopIncident,
)
from apps.maintenance.models import ActionLink, LinkKind, MaintenanceAction
from apps.notifications.models import Alert
from apps.organizations.models import Machine
from apps.organizations.tenancy import scope_to_user
from apps.quality.models import InspectionResult

MAX_LINKED_STOPS = 500


class LinkError(ValueError):
    pass


# Where each kind's object lives, and how to reach its factory.
TARGETS: dict[str, tuple[type, str, str]] = {
    LinkKind.DOWNTIME_EVENT: (DowntimeEvent, "downtime_event", "line__factory"),
    LinkKind.INCIDENT: (LineStopIncident, "incident", "line__factory"),
    LinkKind.ALERT: (Alert, "alert", "factory"),
    LinkKind.INSPECTION_RESULT: (InspectionResult, "inspection_result", "line__factory"),
}


def _visible(model: type, factory_path: str, user: User) -> QuerySet:
    return scope_to_user(model.objects.all(), user, factory_path)


def validate_link(action_factory_id: int, data: dict[str, Any], user: User) -> dict[str, Any]:
    """Model fields for an ActionLink from {kind, id} or a signature; same factory only."""
    kind = data.get("kind")
    if kind == LinkKind.SIGNATURE:
        machine = _visible(Machine, "line__factory", user).filter(pk=data.get("machine")).first()
        if machine is None or machine.line.factory_id != action_factory_id:
            raise LinkError("The signature's machine must be in this action's factory.")
        reason_id, alarm = data.get("reason"), (data.get("alarm_code") or "").strip()
        if bool(reason_id) == bool(alarm):
            raise LinkError("A signature needs a downtime reason or an alarm code (one of them).")
        reason = None
        if reason_id:
            reason = DowntimeReason.objects.filter(
                pk=reason_id, factory_id=action_factory_id
            ).first()
            if reason is None:
                raise LinkError("The signature's reason must be a reason of this factory.")
        return {
            "kind": kind,
            "signature_machine": machine,
            "signature_reason": reason,
            "signature_alarm_code": alarm,
        }
    if kind not in TARGETS:
        raise LinkError(f"Unknown link kind '{kind}'.")
    model, field, factory_path = TARGETS[kind]
    target = _visible(model, factory_path, user).filter(pk=data.get("id")).first()
    if target is None:
        raise LinkError(f"Unknown {kind} {data.get('id')}.")
    factory_id = target.factory_id if kind == LinkKind.ALERT else target.line.factory_id
    if factory_id != action_factory_id:
        raise LinkError(f"The {kind} must belong to this action's factory.")
    return {"kind": kind, field: target}


def add_links(
    action: MaintenanceAction, items: list[dict[str, Any]], user: User
) -> list[ActionLink]:
    created = []
    for item in items:
        fields = validate_link(action.factory_id, item, user)
        if fields["kind"] == LinkKind.SIGNATURE and action.links.filter(kind="signature").exists():
            raise LinkError("This action already has a problem signature.")
        if fields["kind"] != LinkKind.SIGNATURE:
            field = TARGETS[fields["kind"]][1]
            if action.links.filter(**{field: fields[field]}).exists():
                continue  # already linked
        created.append(ActionLink.objects.create(action=action, created_by=user, **fields))
    return created


def signature(action: MaintenanceAction) -> ActionLink | None:
    return (
        action.links.filter(kind=LinkKind.SIGNATURE)
        .select_related("signature_machine__line__factory", "signature_reason")
        .first()
    )


def linked_stops(action: MaintenanceAction) -> list[DowntimeEvent]:
    """Linked stops plus the first observed stops of linked incidents (each once)."""
    ids = set(
        action.links.filter(kind=LinkKind.DOWNTIME_EVENT).values_list(
            "downtime_event_id", flat=True
        )
    )
    incident_ids = action.links.filter(kind=LinkKind.INCIDENT).values_list("incident_id", flat=True)
    ids |= set(
        DowntimeEvent.objects.filter(
            incident_id__in=list(incident_ids), is_first_stop=True
        ).values_list("pk", flat=True)
    )
    return list(
        DowntimeEvent.objects.filter(pk__in=ids, is_obsolete=False)
        .select_related("line__factory", "current_classification__reason", "machine")
        .order_by("started_at")
    )


# --- "Create action from …" -----------------------------------------------------------


def _signature_of(event: DowntimeEvent) -> dict[str, Any]:
    reason = event.current_classification.reason if event.current_classification else None
    if reason is not None:
        return {"kind": "signature", "machine": event.machine_id, "reason": reason.pk}
    if event.alarm_code:
        return {"kind": "signature", "machine": event.machine_id, "alarm_code": event.alarm_code}
    return {}


def _form(
    machine: Machine, title: str, problem: str, links: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "machine": machine.pk,
        "machine_name": machine.name,
        "line": machine.line_id,
        "line_name": machine.line.name,
        "title": title[:200],
        "problem": problem,
        "links": [link for link in links if link],
    }


def prefill(source: str, params: dict[str, str], user: User) -> dict[str, Any]:
    """The form for a new action created from a stop, an alert, recurring stops, a defect
    or a machine: machine, title, problem and the links to create with it."""
    if source == "incident":
        incident = _visible(LineStopIncident, "line__factory", user).get(pk=params.get("id"))
        first = (
            incident.events.filter(is_first_stop=True, is_obsolete=False)
            .select_related("machine__line", "current_classification__reason")
            .order_by("started_at")
            .first()
        )
        if first is None:
            raise LinkError("This line stop has no machine breakdown to act on.")
        alarm = f" ({first.alarm_code})" if first.alarm_code else ""
        return _form(
            first.machine,
            f"{first.machine.name}: line stop #{incident.pk}{alarm}",
            f"Line stop #{incident.pk}, first observed stop {first.machine.name}{alarm}.",
            [
                {"kind": "incident", "id": incident.pk},
                {"kind": "downtime_event", "id": first.pk},
                _signature_of(first),
            ],
        )
    if source == "alert":
        alert = (
            _visible(Alert, "factory", user)
            .select_related("machine__line")
            .get(pk=params.get("id"))
        )
        if alert.machine is None:
            raise LinkError("This alert is not about one machine.")
        links: list[dict[str, Any]] = [{"kind": "alert", "id": alert.pk}]
        if alert.subject_type in ("incident", "downtime_event"):
            links.append({"kind": alert.subject_type, "id": alert.subject_id})
        return _form(alert.machine, f"{alert.machine.name}: alert #{alert.pk}", "", links)
    if source == "recurring":
        machine = (
            _visible(Machine, "line__factory", user)
            .select_related("line")
            .get(pk=params.get("machine"))
        )
        start, end = datetime.fromisoformat(params["start"]), datetime.fromisoformat(params["end"])
        events = DowntimeEvent.objects.filter(
            machine=machine,
            category=DowntimeCategory.BREAKDOWN,
            is_obsolete=False,
            started_at__lt=end,
        ).exclude(ended_at__lte=start)
        if params.get("reason"):
            reason = DowntimeReason.objects.get(pk=params["reason"], factory=machine.line.factory)
            events = events.filter(current_classification__reason=reason)
            label, sig = reason.name, {"reason": reason.pk}
        else:
            alarm = params.get("alarm") or ""
            events = events.filter(alarm_code=alarm)
            label, sig = alarm, {"alarm_code": alarm}
        stops = list(events.order_by("started_at").values_list("pk", flat=True)[:MAX_LINKED_STOPS])
        return _form(
            machine,
            f"{machine.name} · {label}: recurring stops",
            f"{machine.name} stopped {len(stops)} times for {label} between {start:%Y-%m-%d %H:%M} "
            f"and {end:%Y-%m-%d %H:%M} (UTC).",
            [
                {"kind": "signature", "machine": machine.pk, **sig},
                *({"kind": "downtime_event", "id": pk} for pk in stops),
            ],
        )
    if source == "inspection_result":
        result = (
            _visible(InspectionResult, "line__factory", user)
            .select_related("machine__line", "defect_type")
            .get(pk=params.get("id"))
        )
        code = result.defect_type.code if result.defect_type else result.reported_code
        return _form(
            result.machine,
            f"{result.machine.name}: defect {code}",
            f"Defect {code} detected at {result.timestamp:%Y-%m-%d %H:%M} (UTC).",
            [{"kind": "inspection_result", "id": result.pk}],
        )
    if source == "machine":
        machine = (
            _visible(Machine, "line__factory", user).select_related("line").get(pk=params.get("id"))
        )
        return _form(machine, f"{machine.name}: ", "", [])
    raise LinkError(f"Unknown source '{source}'.")
