"""A compact view of a line stop incident, shared by /lines/{id}/status/ and live messages.

Wording: "first observed stop", never "root cause".
"""

from typing import Any

from apps.downtime.models import DowntimeEvent, LineStopIncident
from apps.organizations.models import Machine, ProductionLine


def _machine(machine: Machine) -> dict[str, Any]:
    return {"id": machine.id, "external_id": machine.external_id, "name": machine.name}


def incident_payload(incident: LineStopIncident) -> dict[str, Any]:
    members: list[DowntimeEvent] = sorted(
        incident.events.select_related("machine"),
        key=lambda e: (e.started_at, e.machine.position, e.pk),
    )
    firsts = [m for m in members if m.is_first_stop]
    return {
        "incident_id": incident.id,
        "started_at": incident.started_at,
        "ended_at": incident.ended_at,
        "origin": incident.origin,
        "first_observed_stop": {
            "machines": [_machine(m.machine) for m in firsts],
            "alarm_code": firsts[0].alarm_code if firsts else None,
        },
        "affected_machines": [
            {
                **_machine(m.machine),
                "category": m.category,
                "started_at": m.started_at,
                "ended_at": m.ended_at,
                "is_first_stop": m.is_first_stop,
            }
            for m in members
        ],
    }


def open_incident_summary(line: ProductionLine) -> dict[str, Any] | None:
    incident = (
        LineStopIncident.objects.filter(line=line, ended_at__isnull=True)
        .order_by("-started_at", "-id")
        .first()
    )
    return incident_payload(incident) if incident else None
