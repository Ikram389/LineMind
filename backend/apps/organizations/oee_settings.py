"""Per-factory OEE rule settings (docs/PRODUCT.md §4, which documents each one).

Each factory stores these in `Factory.oee_settings`. Missing keys fall back to
the defaults below. The OEE calculation itself is in apps/analytics/services/oee.py.
"""

from typing import Any

from django.core.exceptions import ValidationError

NO_DATA_AS_DOWNTIME = "downtime"
NO_DATA_EXCLUDED = "exclude"

DEFAULT_OEE_SETTINGS: dict[str, bool | int | str] = {
    # Planned stops and scheduled breaks are excluded from planned production time.
    # If False they stay in planned time and planned stops count as downtime.
    "planned_stops_excluded": True,
    # Stops classified with an "is_changeover" reason count as (unplanned) downtime,
    # unless True: then they are removed from planned production time.
    "changeovers_are_planned": False,
    # Stops shorter than this are not recorded as downtime events
    # (they still reduce performance). Filters sensor flicker.
    "minimum_stop_seconds": 5,
    # Time without data from the counting machine: "downtime" (counted as unplanned
    # downtime) or "exclude" (removed from planned production time).
    "no_data_handling": NO_DATA_AS_DOWNTIME,
}

_SETTING_TYPES: dict[str, type] = {
    "planned_stops_excluded": bool,
    "changeovers_are_planned": bool,
    "minimum_stop_seconds": int,
    "no_data_handling": str,
}
_ALLOWED_VALUES: dict[str, set[str]] = {
    "no_data_handling": {NO_DATA_AS_DOWNTIME, NO_DATA_EXCLUDED},
}


def default_oee_settings() -> dict[str, bool | int | str]:
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
        allowed = _ALLOWED_VALUES.get(key)
        if allowed and item not in allowed:
            raise ValidationError(
                f"OEE setting '{key}' must be one of: {', '.join(sorted(allowed))}."
            )

    if value.get("minimum_stop_seconds", 0) < 0:
        raise ValidationError("OEE setting 'minimum_stop_seconds' cannot be negative.")
