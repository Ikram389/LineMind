"""Default defect catalogue (docs/PRODUCT.md §6) and demo inspection stations (seed_demo)."""

from apps.organizations.models import Machine, Organization, ProductionLine
from apps.quality.models import DefectType, InspectionStation, Severity, StationSource

# (code, name, description, severity)
DEFAULT_DEFECT_TYPES: list[tuple[str, str, str, str]] = [
    ("Q01", "Empty or underfilled bottle", "Fill level below the minimum.", Severity.MAJOR),
    ("Q02", "Missing label", "No label on the bottle.", Severity.MAJOR),
    ("Q03", "Misaligned or wrinkled label", "Label present but badly applied.", Severity.MINOR),
    ("Q04", "Missing or tilted cap", "Can leak or be contaminated.", Severity.CRITICAL),
    (
        "Q05",
        "Unreadable or incorrect batch/date code",
        "Batch or date code fails the OCR check (traceability).",
        Severity.MAJOR,
    ),
    ("Q06", "Damaged bottle", "Cracked, chipped or deformed bottle.", Severity.CRITICAL),
]

# Where the simulator's scenarios inject defects: machine external_id -> (name, codes).
DEMO_STATIONS: dict[str, tuple[str, tuple[str, ...]]] = {
    "M01": ("Bottle inspection (feeder)", ("Q06",)),
    "M03": ("Fill level check (filler)", ("Q01",)),
    "M04": ("Cap check (capper)", ("Q04",)),
    "M05": ("Label and code check (labeler)", ("Q02", "Q03", "Q05")),
    "M06": ("Final check (packer)", ("Q02", "Q04")),
}


def ensure_default_defect_types(organization: Organization) -> dict[str, DefectType]:
    """Create missing types; existing ones (possibly edited by a manager) are left alone."""
    types = {}
    for code, name, description, severity in DEFAULT_DEFECT_TYPES:
        types[code], _ = DefectType.objects.get_or_create(
            organization=organization,
            code=code,
            defaults={"name": name, "description": description, "severity": severity},
        )
    return types


def ensure_demo_stations(line: ProductionLine, types: dict[str, DefectType]) -> int:
    """One station per demo machine, unless that machine already has an active one."""
    created = 0
    for external_id, (name, codes) in DEMO_STATIONS.items():
        machine = Machine.objects.filter(line=line, external_id=external_id).first()
        if (
            machine is None
            or InspectionStation.objects.filter(machine=machine, is_active=True).exists()
        ):
            continue
        station = InspectionStation.objects.create(
            line=line, machine=machine, name=name, source=StationSource.SIMULATOR
        )
        station.defect_types.set([types[code] for code in codes])
        created += 1
    return created
