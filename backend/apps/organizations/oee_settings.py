"""Per-factory OEE rule settings (docs/PRODUCT.md §4 and §5).

Each factory stores these in `Factory.oee_settings`. Missing keys fall back to
the defaults below. These settings only *describe* the rules; the OEE
calculation itself will live in a dedicated service (build step 6).
"""

from typing import Any

from django.core.exceptions import ValidationError

DEFAULT_OEE_SETTINGS: dict[str, bool | int] = {
    # Planned stops and scheduled breaks are excluded from planned production time.
    "planned_stops_excluded": True,
    # Changeovers count as (unplanned) downtime unless set to True here.
    "changeovers_are_planned": False,
    # Stops shorter than this are not recorded as downtime events
    # (they still reduce performance). Filters sensor flicker.
    "minimum_stop_seconds": 5,
}

_SETTING_TYPES: dict[str, type] = {
    "planned_stops_excluded": bool,
    "changeovers_are_planned": bool,
    "minimum_stop_seconds": int,
}


def default_oee_settings() -> dict[str, bool | int]:
    """Return a fresh copy of the defaults (used as the model field default)."""
    return dict(DEFAULT_OEE_SETTINGS)


def with_defaults(settings: dict[str, Any]) -> dict[str, Any]:
    """Fill in any missing keys with their default values."""
    return {**DEFAULT_OEE_SETTINGS, **settings}


def validate_oee_settings(value: Any) -> None:
    if not isinstance(value, dict):
        raise ValidationError("OEE settings must be a JSON object.")

    unknown = sorted(set(value) - set(_SETTING_TYPES))
    if unknown:
        raise ValidationError(f"Unknown OEE setting(s): {', '.join(unknown)}.")

    for key, expected_type in _SETTING_TYPES.items():
        if key not in value:
            continue
        item = value[key]
        # bool is a subclass of int in Python, so check the exact type.
        if type(item) is not expected_type:
            raise ValidationError(f"OEE setting '{key}' must be a {expected_type.__name__}.")

    if value.get("minimum_stop_seconds", 0) < 0:
        raise ValidationError("OEE setting 'minimum_stop_seconds' cannot be negative.")
