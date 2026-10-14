"""Did the problem decrease after the fix? The one place this is computed.

For an action with a problem signature (machine + reason, or machine + alarm) and a fix
date, two windows of equal length are compared: before and after the fix. Both are
counted per 10 hours of RUN TIME, so a quieter production week does not look like an
improvement. The numbers come from the existing services only:
- occurrences and downtime: step 8's analysis (machine view, breakdowns, this machine,
  this reason or alarm, clipped to the window);
- run time: step 6's OEE inputs for the line (planned time minus unplanned downtime).

It is an observation, not proof: the wording says what changed after the fix date.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from django.utils import timezone

from apps.analytics.services.oee import compute_inputs
from apps.analytics.services.oee_data import NoCountingMachineError, load_line_data
from apps.downtime.services.analysis import MACHINE_VIEW, AnalysisFilters, select_entries
from apps.maintenance.models import ActionLink, MaintenanceAction
from apps.maintenance.services.links import signature as action_signature

MARGIN = 0.20  # a change smaller than ±20% of the before rate is "no change"
MIN_BEFORE_OCCURRENCES = 5  # with fewer, a percentage change means nothing
PER_HOURS = 10


def _round(value: float) -> float:
    return round(value, 2)


def measure(link: ActionLink, start: datetime, end: datetime, now: datetime) -> dict[str, Any]:
    machine = link.signature_machine
    line = machine.line
    filters = AnalysisFilters(
        start=start,
        end=end,
        now=now,
        view=MACHINE_VIEW,
        machine_id=machine.pk,
        categories=frozenset({"breakdown"}),
        reason=link.signature_reason.code if link.signature_reason else None,
        alarm=link.signature_alarm_code or None,
    )
    entries = select_entries([line], filters)
    downtime = sum(e.clipped_micros for e in entries) / 1_000_000
    try:
        data, _ = load_line_data(line, start, end, now=now)
        run_hours = float(compute_inputs(data, start, end).run_seconds) / 3600
    except NoCountingMachineError:
        run_hours = 0.0
    per = (lambda value: value / run_hours * PER_HOURS) if run_hours else (lambda value: None)
    occurrences_rate = per(len(entries))
    downtime_rate = per(downtime / 60)
    return {
        "start": start,
        "end": end,
        "occurrences": len(entries),
        "downtime_seconds": _round(downtime),
        "run_hours": _round(run_hours),
        "occurrences_per_10h": None if occurrences_rate is None else _round(occurrences_rate),
        "downtime_minutes_per_10h": None if downtime_rate is None else _round(downtime_rate),
    }


def _signature_dict(link: ActionLink) -> dict[str, Any]:
    return {
        "machine": {"id": link.signature_machine_id, "name": link.signature_machine.name},
        "reason": (
            {
                "id": link.signature_reason_id,
                "code": link.signature_reason.code,
                "name": link.signature_reason.name,
            }
            if link.signature_reason
            else None
        ),
        "alarm_code": link.signature_alarm_code or None,
    }


def effectiveness(action: MaintenanceAction, now: datetime | None = None) -> dict[str, Any]:
    now = now or timezone.now()
    link = action_signature(action)
    base: dict[str, Any] = {
        "fixed_at": action.fixed_at,
        "window_days": action.effectiveness_window_days,
        "min_after_run_hours": action.min_after_run_hours,
        "min_before_occurrences": MIN_BEFORE_OCCURRENCES,
        "margin": MARGIN,
        "signature": _signature_dict(link) if link else None,
    }
    if link is None:
        return {**base, "status": "no_signature"}
    if action.fixed_at is None:
        return {**base, "status": "not_fixed"}

    window = timedelta(days=action.effectiveness_window_days)
    fixed = action.fixed_at
    before = measure(link, fixed - window, fixed, now)
    after = measure(link, fixed, min(fixed + window, now), now) if now > fixed else None
    result = {**base, "before": before, "after": after}

    after_hours = after["run_hours"] if after else 0.0
    if after_hours < action.min_after_run_hours:
        return {
            **result,
            "status": "not_enough_data",
            "reason": "after_run_time",
            "missing_run_hours": _round(action.min_after_run_hours - after_hours),
        }
    if not before["run_hours"]:
        return {**result, "status": "not_enough_data", "reason": "before_run_time"}
    if before["occurrences"] < MIN_BEFORE_OCCURRENCES:
        return {**result, "status": "not_enough_data", "reason": "few_occurrences_before"}

    old, new = before["occurrences_per_10h"], after["occurrences_per_10h"]
    if new <= old * (1 - MARGIN):
        status, key = "improved", "effect.fell"
    elif new >= old * (1 + MARGIN):
        status, key = "worse", "effect.rose"
    else:
        status, key = "no_change", "effect.similar"
    return {
        **result,
        "status": status,
        "message_key": key,
        "message_values": {"from": old, "to": new},
    }
