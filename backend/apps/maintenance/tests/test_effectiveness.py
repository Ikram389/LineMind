"""Before/after effectiveness: per 10 run hours, from the step 6 and step 8 functions."""

from collections.abc import Callable
from datetime import UTC, datetime, time, timedelta

import pytest

from apps.analytics.services.oee import compute_inputs
from apps.analytics.services.oee_data import load_line_data
from apps.downtime.models import DowntimeEvent
from apps.downtime.services.analysis import AnalysisFilters, select_entries
from apps.maintenance.models import MaintenanceAction
from apps.maintenance.services.effectiveness import MIN_BEFORE_OCCURRENCES, effectiveness
from apps.production.models import Shift
from tests.helpers import ApiFactory, World
from tests.lines import Bottling

FIX = datetime(2026, 9, 30, 5, 0, tzinfo=UTC)  # between the two 24-hour fixtures
Send = Callable[..., str]


def signature_action(
    new_action: Callable[..., MaintenanceAction], bottling: Bottling, fixed_at: datetime, days: int
) -> MaintenanceAction:
    action = new_action(
        "done",
        links=[
            {"kind": "signature", "machine": bottling.machines["M05"].pk, "alarm_code": "E-204"}
        ],
        effectiveness_window_days=days,
    )
    MaintenanceAction.objects.filter(pk=action.pk).update(fixed_at=fixed_at)
    action.refresh_from_db()
    return action


@pytest.fixture
def real_shift(bottling: Bottling) -> Shift:
    """24-hour shifts with the factory's normal 60 s stale threshold (not relaxed): the
    simulator data must be dense enough to never look like missing data."""
    assert bottling.line.factory.stale_after_seconds == 60
    return Shift.objects.create(
        factory=bottling.line.factory, name="All day", start_time=time(0), end_time=time(0)
    )


def test_the_recurring_jams_drop_after_the_fix(
    real_shift: Shift,
    load: Callable[..., None],
    bottling: Bottling,
    new_action: Callable[..., MaintenanceAction],
    world: World,
    api: ApiFactory,
) -> None:
    load("labeler_recurring_jams_24h", batch_size=1000)
    load("labeler_after_fix_24h", batch_size=1000)
    action = signature_action(new_action, bottling, FIX, days=1)
    now = FIX + timedelta(days=2)

    result = effectiveness(action, now=now)

    # The simulator data has no gaps: no "no data" time on any machine.
    assert not DowntimeEvent.objects.filter(category="no_data").exists()
    assert result["status"] == "improved"
    before, after = result["before"], result["after"]
    assert before["occurrences"] >= 20 and after["occurrences"] <= 6
    assert before["run_hours"] > 20 and after["run_hours"] > 20
    assert after["occurrences_per_10h"] < before["occurrences_per_10h"] * 0.8
    assert result["message_key"] == "effect.fell"
    assert result["message_values"] == {
        "from": before["occurrences_per_10h"],
        "to": after["occurrences_per_10h"],
    }

    # The numbers are exactly the step 8 analysis and the step 6 OEE run time.
    for window in (before, after):
        entries = select_entries(
            [bottling.line],
            AnalysisFilters(
                start=window["start"],
                end=window["end"],
                now=now,
                view="machine",
                machine_id=bottling.machines["M05"].pk,
                categories=frozenset({"breakdown"}),
                alarm="E-204",
            ),
        )
        data, _ = load_line_data(bottling.line, window["start"], window["end"], now=now)
        run = float(compute_inputs(data, window["start"], window["end"]).run_seconds) / 3600
        assert window["occurrences"] == len(entries)
        assert window["downtime_seconds"] == round(sum(e.clipped_micros for e in entries) / 1e6, 2)
        assert window["run_hours"] == round(run, 2)
        assert window["occurrences_per_10h"] == round(len(entries) / run * 10, 2)

    body = api(world.users["analyst"]).get(
        f"/api/v1/maintenance-actions/{action.id}/effectiveness/"
    )
    assert body.json()["status"] == "improved"


# --- Hand-made data: one jam pattern per window ------------------------------------------------


def line_runs(
    send: Send,
    start: datetime,
    end: datetime,
    jam_every: timedelta | None,
    planned_stop: tuple[datetime, datetime] | None = None,
) -> None:
    """The packer (counting machine) runs; the labeler jams with E-204 every `jam_every`
    while the line runs; an optional planned stop removes time from planned production."""
    send("M06", "machine_started", start)
    send("M05", "machine_started", start)
    if planned_stop:
        send("M06", "planned_stop_started", planned_stop[0])
        send("M06", "planned_stop_ended", planned_stop[1])
    if jam_every is None:
        return
    at = start + jam_every
    while at < end:
        if not planned_stop or not planned_stop[0] <= at < planned_stop[1]:
            send("M05", "machine_stopped", at, alarm_code="E-204")
            send("M05", "machine_started", at + timedelta(seconds=60))
        at += jam_every


F = datetime(2026, 10, 6, 0, 0, tzinfo=UTC)


@pytest.fixture
def quiet(all_day_shift: Shift) -> Shift:
    return all_day_shift


def test_a_quieter_week_with_the_same_rate_is_no_change(
    quiet: Shift, send: Send, bottling: Bottling, new_action: Callable[..., MaintenanceAction]
) -> None:
    line_runs(send, F - timedelta(days=1), F, timedelta(hours=2))  # 11 jams in 24 run hours
    # After: production stopped (planned) for 12 hours, the same jam rate while running.
    line_runs(
        send,
        F,
        F + timedelta(days=1),
        timedelta(hours=2),
        planned_stop=(F + timedelta(seconds=1), F + timedelta(hours=12)),
    )
    action = signature_action(new_action, bottling, F, days=1)
    action.min_after_run_hours = 10  # 12 run hours after the fix: enough for this comparison
    action.save()

    result = effectiveness(action, now=F + timedelta(days=2))

    before, after = result["before"], result["after"]
    assert after["occurrences"] < before["occurrences"]  # fewer stops in total…
    assert after["run_hours"] == pytest.approx(
        before["run_hours"] / 2, rel=0.02
    )  # …in half the run time
    assert result["status"] == "no_change"


def test_more_stops_per_run_hour_is_worse(
    quiet: Shift, send: Send, bottling: Bottling, new_action: Callable[..., MaintenanceAction]
) -> None:
    line_runs(send, F - timedelta(days=1), F, timedelta(hours=2))
    line_runs(send, F, F + timedelta(days=1), timedelta(hours=1))
    action = signature_action(new_action, bottling, F, days=1)

    assert effectiveness(action, now=F + timedelta(days=2))["status"] == "worse"


def test_not_enough_run_time_after_the_fix(
    quiet: Shift, send: Send, bottling: Bottling, new_action: Callable[..., MaintenanceAction]
) -> None:
    line_runs(send, F - timedelta(days=1), F, timedelta(hours=2))
    line_runs(send, F, F + timedelta(hours=8), None)
    action = signature_action(new_action, bottling, F, days=1)

    result = effectiveness(action, now=F + timedelta(hours=8))

    assert (result["status"], result["reason"]) == ("not_enough_data", "after_run_time")
    assert result["missing_run_hours"] == pytest.approx(12, abs=0.1)  # 20 h needed, 8 h so far


def test_too_few_occurrences_before_the_fix(
    quiet: Shift, send: Send, bottling: Bottling, new_action: Callable[..., MaintenanceAction]
) -> None:
    line_runs(
        send, F - timedelta(days=1), F, timedelta(hours=6)
    )  # 3 jams: 0 after looks like -100%
    line_runs(send, F, F + timedelta(days=1), None)
    action = signature_action(new_action, bottling, F, days=1)

    result = effectiveness(action, now=F + timedelta(days=2))

    assert result["before"]["occurrences"] == 3 < MIN_BEFORE_OCCURRENCES
    assert (result["status"], result["reason"]) == ("not_enough_data", "few_occurrences_before")


def test_without_a_signature_or_a_fix(
    new_action: Callable[..., MaintenanceAction], bottling: Bottling
) -> None:
    assert effectiveness(new_action("in_progress"))["status"] == "no_signature"
    action = new_action(
        "in_progress",
        links=[
            {"kind": "signature", "machine": bottling.machines["M05"].pk, "alarm_code": "E-204"}
        ],
    )
    assert effectiveness(action)["status"] == "not_fixed"
