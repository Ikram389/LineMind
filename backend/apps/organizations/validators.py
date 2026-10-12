from functools import lru_cache
from zoneinfo import available_timezones

from django.core.exceptions import ValidationError


@lru_cache(maxsize=1)
def _known_timezones() -> frozenset[str]:
    return frozenset(available_timezones())


def validate_timezone(value: str) -> None:
    """Accept only IANA timezone names such as 'Africa/Algiers'."""
    if value not in _known_timezones():
        raise ValidationError(f"'{value}' is not a valid IANA timezone (e.g. 'Africa/Algiers').")
