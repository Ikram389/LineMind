"""Default downtime reason catalogue for bottling lines (added per factory by seed_demo)."""

from apps.downtime.models import DowntimeReason, ReasonCategory
from apps.organizations.models import Factory

DEFAULT_REASONS: list[tuple[str, str, str]] = [
    ("MECH-JAM", "Jam / blockage", ReasonCategory.MECHANICAL),
    ("MECH-WEAR", "Worn part", ReasonCategory.MECHANICAL),
    ("MECH-ADJUST", "Adjustment", ReasonCategory.MECHANICAL),
    ("ELEC-SENSOR", "Sensor fault", ReasonCategory.ELECTRICAL),
    ("ELEC-DRIVE", "Motor / drive fault", ReasonCategory.ELECTRICAL),
    ("MAT-LABEL", "Label roll empty", ReasonCategory.MATERIAL),
    ("MAT-CAPS", "Caps shortage", ReasonCategory.MATERIAL),
    ("MAT-BOTTLES", "Bottle shortage", ReasonCategory.MATERIAL),
    ("QUAL-REJECTS", "High reject rate", ReasonCategory.QUALITY),
    ("QUAL-CHECK", "Quality check", ReasonCategory.QUALITY),
    ("ORG-OPERATOR", "Operator absent", ReasonCategory.ORGANIZATIONAL),
    ("ORG-WAITING", "Waiting for instructions", ReasonCategory.ORGANIZATIONAL),
    ("PLAN-BREAK", "Break", ReasonCategory.PLANNED),
    ("PLAN-CLEANING", "Cleaning", ReasonCategory.PLANNED),
    ("PLAN-CHANGEOVER", "Product changeover", ReasonCategory.PLANNED),
    ("PLAN-MAINTENANCE", "Planned maintenance", ReasonCategory.PLANNED),
]


# Reasons whose stops count as changeovers (see the changeovers_are_planned OEE setting).
CHANGEOVER_CODES = frozenset({"PLAN-CHANGEOVER"})


def ensure_default_reasons(factory: Factory) -> int:
    """Add any missing default reasons to the factory. Returns how many were created."""
    created = 0
    for code, name, category in DEFAULT_REASONS:
        reason, was_created = DowntimeReason.objects.get_or_create(
            factory=factory,
            code=code,
            defaults={
                "name": name,
                "category": category,
                "is_changeover": code in CHANGEOVER_CODES,
            },
        )
        if code in CHANGEOVER_CODES and not reason.is_changeover:
            reason.is_changeover = True
            reason.save(update_fields=["is_changeover"])
        created += int(was_created)
    return created
