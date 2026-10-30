"""Preparing the Demo Beverages data for recording a demo video (development only).

- reset(): seed_demo again (idempotent), resolve open alerts, mark the demo users'
  notifications read, delete assistant conversations. History is kept: raw events, stops,
  defects and maintenance actions are never deleted.
- set_long_stop_minutes(): the "Long line stop" rule's threshold (audited, like any
  configuration change).
- ensure_effectiveness_action(): the "Labeler · E-204" maintenance story for the video. It
  loads one day of recurring labeler jams and one day after the fix (the backend test fixtures,
  moved to 19-21 Oct 2026, a stretch with no other demo data) through the real ingestion
  service, then walks a maintenance action through the real workflow: request with the
  signature and the linked jams, assign, start, confirmed diagnosis applied to the stops,
  complete (fix date 20 Oct 05:00 UTC), verify. 1-day windows, so the before/after result
  is "improved". The first run takes a minute or two; later runs reuse it.
- unreviewed_defects(): inspection results nobody has reviewed yet.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.assistant.models import Conversation
from apps.audit.mixins import snapshot
from apps.audit.services import record_audit
from apps.downtime.models import DowntimeEvent, DowntimeReason
from apps.maintenance.models import MaintenanceAction, VerificationResult
from apps.maintenance.models import Status as MaintenanceStatus
from apps.maintenance.services.actions import create_action
from apps.maintenance.services.diagnosis import record_diagnosis
from apps.maintenance.services.effectiveness import effectiveness
from apps.maintenance.services.workflow import transition, verify
from apps.notifications.models import Alert, AlertRule, AlertStatus, Notification, RuleType
from apps.notifications.services.actions import resolve_manually
from apps.organizations.models import Machine, Organization, ProductionLine, Role
from apps.production.models import IngestedEvent, LineApiKey
from apps.production.services.api_keys import create_line_api_key
from apps.production.services.ingestion import ingest_batch
from apps.quality.models import InspectionResult

DEMO_ORGANIZATION = "Demo Beverages"
RESET_NOTE = "Closed by demo_reset before recording a demo."

ACTION_TITLE = "Labeler · E-204: recurring jams"
HISTORY_FIXTURES = ("labeler_recurring_jams_24h", "labeler_after_fix_24h")
FIXTURES = Path(settings.BASE_DIR) / "tests" / "fixtures"
FIXTURE_FIXED_AT = datetime(2026, 9, 30, 5, 0, tzinfo=UTC)  # where the fixtures switch
FIXED_AT = datetime(2026, 10, 20, 5, 0, tzinfo=UTC)
# Event ids are re-derived, so the copy never collides with other runs of the same scenarios.
NAMESPACE = uuid.UUID("0b8f2f7e-4f0e-4d52-8a8e-3c1d5e7a9b21")


def demo_organization() -> Organization:
    return Organization.objects.get(name=DEMO_ORGANIZATION)


def _operator_user(organization: Organization) -> User:
    """The demo platform admin acts for the reset (resolving alerts needs a person)."""
    user = User.objects.filter(
        membership__organization=organization, membership__role=Role.PLATFORM_ADMIN
    ).first()
    if user is None:
        raise RuntimeError("No platform admin in Demo Beverages: run seed_demo first.")
    return user


def reset() -> dict[str, int]:
    call_command("seed_demo", stdout=StringIO())
    organization = demo_organization()
    admin = _operator_user(organization)
    open_alerts = Alert.objects.filter(factory__organization=organization).exclude(
        status=AlertStatus.RESOLVED
    )
    resolved = 0
    for alert in open_alerts:
        resolve_manually(alert, admin, RESET_NOTE)
        resolved += 1
    read = mark_notifications_read(organization)
    conversations, _ = Conversation.objects.filter(organization=organization).delete()
    return {
        "alerts_resolved": resolved,
        "notifications_read": read,
        "conversations_deleted": conversations,
    }


def mark_notifications_read(organization: Organization) -> int:
    return Notification.objects.filter(
        user__membership__organization=organization, read_at__isnull=True
    ).update(read_at=timezone.now())


def set_long_stop_minutes(minutes: int) -> list[AlertRule]:
    organization = demo_organization()
    rules = list(
        AlertRule.objects.filter(factory__organization=organization, rule_type=RuleType.LONG_STOP)
    )
    if not rules:
        raise RuntimeError("Demo Beverages has no long-stop alert rule: run seed_demo first.")
    for rule in rules:
        with transaction.atomic():
            before = snapshot(rule)
            rule.parameters = {**rule.parameters, "minutes": minutes}
            rule.save(update_fields=["parameters"])
            record_audit(
                user=None,
                action="alertrule.updated",
                entity=rule,
                organization=organization,
                before=before,
                after=snapshot(rule),
            )
    return rules


def unreviewed_defects() -> int:
    return InspectionResult.objects.filter(
        line__factory__organization=demo_organization(), current_review__isnull=True
    ).count()


def action_url(action: MaintenanceAction) -> str:
    return f"{settings.FRONTEND_URL}/maintenance/{action.pk}"


def _demo_user(role: Role) -> User:
    return User.objects.get(email=f"{role.value}@demo-beverages.test")


def _history(line: ProductionLine) -> list[dict[str, object]]:
    shift = FIXED_AT - FIXTURE_FIXED_AT
    events = []
    for fixture in HISTORY_FIXTURES:
        with (FIXTURES / f"{fixture}.jsonl").open(encoding="utf-8") as handle:
            for row in handle:
                if not row.strip():
                    continue
                event = json.loads(row)
                moved = datetime.fromisoformat(event["timestamp"]) + shift
                event["timestamp"] = moved.isoformat()
                event["event_id"] = str(uuid.uuid5(NAMESPACE, f"{line.pk}|{event['event_id']}"))
                events.append(event)
    return events


def load_history(line: ProductionLine) -> int:
    """Send the two days through the ingestion service once; returns the events created."""
    events = _history(line)
    if IngestedEvent.objects.filter(event_id=events[-1]["event_id"]).exists():
        return 0  # already loaded by an earlier run
    key = LineApiKey.objects.filter(line=line, revoked_at__isnull=True).first()
    if key is None:
        key, _ = create_line_api_key(line, "Demo video history loader")
    created = 0
    for i in range(0, len(events), 1000):
        created += sum(r.status == "created" for r in ingest_batch(key, events[i : i + 1000]))
    return created


def _jams_before_fix(labeler: Machine) -> list[DowntimeEvent]:
    return list(
        DowntimeEvent.objects.filter(
            machine=labeler,
            category="breakdown",
            alarm_code="E-204",
            is_obsolete=False,
            started_at__gte=FIXED_AT - timedelta(days=1),
            started_at__lt=FIXED_AT,
        ).order_by("started_at")
    )


def _build_action(labeler: Machine) -> MaintenanceAction:
    supervisor = _demo_user(Role.PRODUCTION_SUPERVISOR)
    technician = _demo_user(Role.MAINTENANCE_TECHNICIAN)
    links: list[dict[str, object]] = [
        {"kind": "signature", "machine": labeler.pk, "alarm_code": "E-204"}
    ]
    links += [{"kind": "downtime_event", "id": stop.pk} for stop in _jams_before_fix(labeler)]
    action = create_action(
        supervisor,
        labeler,
        {
            "title": ACTION_TITLE,
            "problem": "The labeler jams with alarm E-204 several times an hour.",
            "priority": "high",
            "assignee": technician,
            "effectiveness_window_days": 1,
        },
        links,
    )
    action = transition(action, MaintenanceStatus.ASSIGNED, supervisor)
    action = transition(action, MaintenanceStatus.IN_PROGRESS, technician)
    jam = DowntimeReason.objects.get(factory=labeler.line.factory, code="MECH-JAM")
    record_diagnosis(
        action,
        jam,
        "Worn label guide rollers: labels skew and jam the applicator.",
        technician,
        apply_to_stops=True,
    )
    action = transition(
        action,
        MaintenanceStatus.DONE,
        technician,
        note="Replaced the label guide rollers and re-aligned the applicator.",
        fixed_at=FIXED_AT,
    )
    return verify(
        action,
        VerificationResult.EFFECTIVE,
        "No E-204 jams since the rollers were replaced.",
        supervisor,
    )


def ensure_effectiveness_action() -> tuple[MaintenanceAction, dict[str, object]]:
    """The verified Labeler E-204 action, created on the first run; returns its result."""
    organization = demo_organization()
    line = ProductionLine.objects.filter(factory__organization=organization).order_by("pk").first()
    if line is None:
        raise RuntimeError("Demo Beverages has no line: run seed_demo first.")
    labeler = line.machines.get(external_id="M05")
    load_history(line)
    action = (
        MaintenanceAction.objects.filter(line=line, title=ACTION_TITLE)
        .exclude(status=MaintenanceStatus.CANCELLED)
        .first()
    )
    if action is None:
        action = _build_action(labeler)
        mark_notifications_read(organization)  # the assignment and completion messages
    return action, effectiveness(action)
