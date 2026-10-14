"""English text for alert emails, by message key.

The web app has its own copy of these sentences (frontend/src/i18n/en.ts, keys "alert.*").
Alerts store only the key and its values, so both can be translated later.
"""

from string import Formatter
from typing import Any

EMAIL_MESSAGES: dict[str, str] = {
    "alert.long_stop": (
        "Line stopped for more than {minutes} min: first observed stop {machine}{alarm_text}."
    ),
    "alert.long_stop_unknown": (
        "Line stopped for more than {minutes} min (no machine breakdown observed)."
    ),
    "alert.long_breakdown": "{machine} has been stopped for more than {minutes} min{alarm_text}.",
    "alert.recurring_stop": (
        "{machine} stopped {count} times in {hours} h for the same reason: {reason}."
    ),
    "alert.recurring_stop_alarm": (
        "{machine} stopped {count} times in {hours} h with alarm {alarm}."
    ),
    "alert.machine_offline": "No data from {machine} for more than {minutes} min.",
    "alert.line_offline": "No data from any machine of {line} for more than {minutes} min.",
    "alert.low_oee": "OEE of {shift} is {oee}%, below {threshold}%.",
    "alert.high_defect_rate": (
        "Defect rate {rate}% in the last {minutes} min (above {threshold}%): "
        "{defects} defects in {units} bottles."
    ),
    "alert.high_defect_rate_station": (
        "Defect rate at {station} {rate}% in the last {minutes} min (above {threshold}%)."
    ),
    "alert.unclassified_stop": (
        "A stop at {machine} still has no reason {minutes} min after it ended."
    ),
}

SEVERITY_LABELS = {"info": "Info", "warning": "Warning", "critical": "Critical"}


class _Defaults(dict[str, Any]):
    def __missing__(self, key: str) -> str:
        return ""


def render_message(key: str, values: dict[str, Any]) -> str:
    template = EMAIL_MESSAGES.get(key, key)
    filled = _Defaults(values)
    filled["alarm_text"] = f" (alarm {values['alarm']})" if values.get("alarm") else ""
    return Formatter().vformat(template, (), filled)
