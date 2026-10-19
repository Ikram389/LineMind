"""The evaluation's own data: an "Assistant Eval" organization, apart from the demo data.

Three lines, each fed with a known simulator fixture through the real ingestion service:
- Eval Line 1: normal_shift_150m (Mon 5 Oct 2026, 06:00–08:30 UTC), with two production
  orders (a changeover at 07:15 UTC) and inspection stations.
- Eval Line 2: labeler_jam (Mon 12 Oct 2026, 10:00–10:15 UTC).
- Eval Line 3: labeler_recurring_jams_24h then labeler_after_fix_24h (29 Sep → 1 Oct),
  with a completed maintenance action fixed at 30 Sep 05:00 UTC.

Event ids are re-derived per line, so loading never collides with demo data that came
from the same scenarios. Everything is idempotent: run it as often as you like.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from pathlib import Path

from django.conf import settings

from apps.accounts.models import User
from apps.assistant.models import AssistantSettings
from apps.downtime.default_reasons import ensure_default_reasons
from apps.maintenance.models import ActionLink, MaintenanceAction
from apps.organizations.models import (
    Factory,
    Machine,
    Membership,
    Organization,
    ProductionLine,
    Role,
)
from apps.production.models import LineApiKey, OrderStatus, Product, ProductionOrder, Shift
from apps.production.services.api_keys import create_line_api_key
from apps.production.services.ingestion import ingest_batch
from apps.quality.defaults import ensure_default_defect_types, ensure_demo_stations

ORGANIZATION = "Assistant Eval"
USER_EMAIL = "assistant.eval@linemind.test"
FIXTURES = Path(settings.BASE_DIR) / "tests" / "fixtures"
NAMESPACE = uuid.UUID("6f1c4a52-9a3e-4c5e-9d55-6a2b2f6f0c10")
MACHINES = [
    ("M01", "Bottle feeder"),
    ("M02", "Rinser"),
    ("M03", "Filler"),
    ("M04", "Capper"),
    ("M05", "Labeler"),
    ("M06", "Packer"),
]
LINE_FIXTURES = {
    "Eval Line 1": ["normal_shift_150m"],
    "Eval Line 2": ["labeler_jam"],
    "Eval Line 3": ["labeler_recurring_jams_24h", "labeler_after_fix_24h"],
}
CHANGEOVER = datetime(2026, 10, 5, 7, 15, tzinfo=UTC)
FIXED_AT = datetime(2026, 9, 30, 5, 0, tzinfo=UTC)


@dataclass
class EvalWorld:
    organization: Organization
    factory: Factory
    user: User
    lines: dict[str, ProductionLine]
    action: MaintenanceAction | None


def _line(factory: Factory, name: str) -> ProductionLine:
    line, _ = ProductionLine.objects.get_or_create(factory=factory, name=name)
    for position, (external_id, label) in enumerate(MACHINES, start=1):
        Machine.objects.get_or_create(
            line=line,
            external_id=external_id,
            defaults={
                "name": label,
                "machine_type": label.lower(),
                "position": position,
                "nominal_speed_per_hour": 6000,
            },
        )
    return line


def _load(line: ProductionLine, fixture: str) -> int:
    key = LineApiKey.objects.filter(line=line, revoked_at__isnull=True).first()
    if key is None:
        key, _ = create_line_api_key(line, "Assistant evaluation loader")
    with (FIXTURES / f"{fixture}.jsonl").open(encoding="utf-8") as handle:
        events = [json.loads(row) for row in handle if row.strip()]
    for event in events:
        event["event_id"] = str(uuid.uuid5(NAMESPACE, f"{line.name}|{event['event_id']}"))
    created = 0
    for i in range(0, len(events), 1000):
        created += sum(r.status == "created" for r in ingest_batch(key, events[i : i + 1000]))
    return created


def _orders(line: ProductionLine, organization: Organization) -> None:
    water, _ = Product.objects.get_or_create(
        organization=organization,
        sku="W50",
        defaults={"name": "Water 0.5 L", "ideal_cycle_time_seconds": 0.6},
    )
    juice, _ = Product.objects.get_or_create(
        organization=organization,
        sku="J33",
        defaults={"name": "Juice 0.33 L", "ideal_cycle_time_seconds": 0.6},
    )
    start = datetime(2026, 10, 5, 5, 0, tzinfo=UTC)
    for product, begin, end in (
        (water, start, CHANGEOVER),
        (juice, CHANGEOVER, start + timedelta(hours=4)),
    ):
        ProductionOrder.objects.get_or_create(
            line=line,
            product=product,
            scheduled_start=begin,
            defaults={
                "scheduled_end": end,
                "planned_quantity": 10000,
                "status": OrderStatus.COMPLETED,
            },
        )


def _action(line: ProductionLine, user: User) -> MaintenanceAction:
    labeler = line.machines.get(external_id="M05")
    action, created = MaintenanceAction.objects.get_or_create(
        line=line,
        title="Labeler jams E-204",
        defaults={
            "factory": line.factory,
            "machine": labeler,
            "problem": "The labeler jams with alarm E-204 several times an hour.",
            "status": "done",
            "reporter": user,
            "assignee": user,
            "started_at": FIXED_AT - timedelta(hours=1),
            "completed_at": FIXED_AT,
            "fixed_at": FIXED_AT,
            "effectiveness_window_days": 1,
        },
    )
    if created:
        ActionLink.objects.create(
            action=action,
            kind="signature",
            signature_machine=labeler,
            signature_alarm_code="E-204",
            created_by=user,
        )
    return action


def build(lines: list[str] | None = None) -> EvalWorld:
    """Create (or refresh) the evaluation data. `lines` limits which lines get their events."""
    organization, _ = Organization.objects.get_or_create(name=ORGANIZATION)
    factory, _ = Factory.objects.get_or_create(
        organization=organization, name="Eval Plant", defaults={"timezone": "Africa/Algiers"}
    )
    for name, start, end in (("Morning", 6, 14), ("Afternoon", 14, 22), ("Night", 22, 6)):
        Shift.objects.get_or_create(
            factory=factory, name=name, defaults={"start_time": time(start), "end_time": time(end)}
        )
    ensure_default_reasons(factory)
    types = ensure_default_defect_types(organization)
    user = User.objects.filter(email=USER_EMAIL).first()
    if user is None:
        user = User.objects.create_user(email=USER_EMAIL, password=None)
        Membership.objects.create(
            user=user,
            organization=organization,
            role=Role.PRODUCTION_SUPERVISOR,
            all_factories=True,
        )
    AssistantSettings.objects.update_or_create(
        organization=organization, defaults={"enabled": True}
    )

    built = {name: _line(factory, name) for name in LINE_FIXTURES}
    ensure_demo_stations(built["Eval Line 1"], types)
    _orders(built["Eval Line 1"], organization)
    action = _action(built["Eval Line 3"], user)
    for name in lines or list(LINE_FIXTURES):
        for fixture in LINE_FIXTURES[name]:
            _load(built[name], fixture)
    return EvalWorld(organization, factory, user, built, action)
