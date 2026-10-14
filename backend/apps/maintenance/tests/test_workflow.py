"""The status workflow: allowed steps work, everything else is refused; notes; audit; roles."""

from collections.abc import Callable
from datetime import timedelta
from itertools import product
from typing import Any

import pytest
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.maintenance.models import MaintenanceAction, MaintenanceStatusChange, Status
from apps.maintenance.services.workflow import STEPS, NotAllowed, WorkflowError, transition, verify
from tests.helpers import ApiFactory, World

ALL = list(Status.values)
URL = "/api/v1/maintenance-actions/"


def post_step(api: ApiFactory, user: Any, action: MaintenanceAction, to: str, **body: Any) -> Any:
    return api(user).post(f"{URL}{action.id}/transition/", {"to": to, **body}, format="json")


@pytest.mark.parametrize(("src", "to"), sorted(STEPS))
def test_every_allowed_step_works(
    src: str, to: str, new_action: Callable[..., MaintenanceAction], world: World, api: ApiFactory
) -> None:
    action = new_action(src)
    note = "because" if STEPS[(src, to)].note_required else ""
    user = world.users[
        "production_supervisor"
        if STEPS[(src, to)].who.startswith("supervisor")
        else "maintenance_technician"
    ]
    body: dict[str, Any] = {"note": note}
    if to == "assigned":
        body["assignee"] = world.users["maintenance_technician"].id

    response = post_step(api, user, action, to, **body)

    assert response.status_code == 200, response.json()
    assert response.json()["status"] == to
    change = MaintenanceStatusChange.objects.filter(action=action).last()
    assert (change.from_status, change.to_status, change.note) == (src, to, note)
    assert AuditLog.objects.filter(
        entity_id=str(action.id), action=f"maintenance.{STEPS[(src, to)].event}"
    ).exists()


INVALID = [(s, t) for s, t in product(ALL, ALL) if (s, t) not in STEPS and s != t]


@pytest.mark.parametrize(("src", "to"), INVALID)
def test_every_other_step_is_refused(
    src: str, to: str, new_action: Callable[..., MaintenanceAction], world: World, api: ApiFactory
) -> None:
    action = new_action(src)

    response = post_step(api, world.users["factory_manager"], action, to, note="x")

    assert response.status_code == 400
    action.refresh_from_db()
    assert action.status == src


@pytest.mark.parametrize(
    ("src", "to"), [(s, t) for (s, t), step in STEPS.items() if step.note_required]
)
def test_cancel_reopen_and_wait_need_a_note(
    src: str, to: str, new_action: Callable[..., MaintenanceAction], world: World
) -> None:
    action = new_action(src)
    who = STEPS[(src, to)].who
    user = world.users["maintenance_technician" if who == "worker" else "factory_manager"]
    with pytest.raises(WorkflowError, match="note is required"):
        transition(action, to, user, note="  ")


def test_timestamps_and_fix_date(
    new_action: Callable[..., MaintenanceAction], world: World
) -> None:
    action = new_action("in_progress")
    assert action.started_at is not None
    tech = world.users["maintenance_technician"]
    with pytest.raises(WorkflowError, match="future"):
        transition(action, "done", tech, fixed_at=timezone.now() + timedelta(hours=1))

    earlier = timezone.now() - timedelta(days=2)
    action = transition(action, "done", tech, fixed_at=earlier)
    assert action.fixed_at == earlier and action.completed_at > earlier

    action = verify(action, "effective", "Jams stopped", world.users["production_supervisor"])
    assert (action.status, action.verification_result) == ("verified", "effective")
    action = transition(action, "in_progress", tech, note="Jams are back")
    assert (action.completed_at, action.fixed_at, action.verification_result) == (None, None, "")
    events = list(
        MaintenanceStatusChange.objects.filter(action=action).values_list("event", flat=True)
    )
    assert events == ["assign", "start", "complete", "verify", "reopen"]


def test_verify_only_from_done_with_a_result(
    new_action: Callable[..., MaintenanceAction], world: World, api: ApiFactory
) -> None:
    action = new_action("in_progress")
    url = f"{URL}{action.id}/verify/"
    supervisor = api(world.users["production_supervisor"])
    assert supervisor.post(url, {"result": "effective"}, format="json").status_code == 400

    done = new_action("done")
    assert (
        supervisor.post(f"{URL}{done.id}/verify/", {"result": "maybe"}, format="json").status_code
        == 400
    )
    assert (
        api(world.users["maintenance_technician"])
        .post(f"{URL}{done.id}/verify/", {"result": "effective"}, format="json")
        .status_code
        == 403
    )
    ok = supervisor.post(
        f"{URL}{done.id}/verify/", {"result": "not_effective", "note": "Still jams"}, format="json"
    )
    assert ok.status_code == 200
    assert (ok.json()["status"], ok.json()["verification_result"]) == ("verified", "not_effective")


@pytest.mark.parametrize(
    ("user", "src", "to", "allowed"),
    [
        ("production_supervisor", "requested", "assigned", True),
        ("factory_manager", "requested", "assigned", True),
        ("maintenance_technician", "requested", "assigned", False),
        ("machine_operator", "requested", "assigned", False),
        ("maintenance_technician", "assigned", "in_progress", True),
        ("machine_operator", "assigned", "in_progress", False),
        ("production_supervisor", "assigned", "in_progress", False),  # not the assignee
        ("maintenance_technician", "in_progress", "done", True),
        ("analyst", "in_progress", "done", False),
        ("machine_operator", "requested", "cancelled", True),  # the reporter, still requested
        ("machine_operator", "assigned", "cancelled", False),
        ("maintenance_technician", "done", "in_progress", True),
        ("quality_inspector", "done", "in_progress", False),
    ],
)
def test_roles_for_each_step(
    user: str,
    src: str,
    to: str,
    allowed: bool,
    new_action: Callable[..., MaintenanceAction],
    world: World,
) -> None:
    action = new_action(src)
    kwargs: dict[str, Any] = {"note": "because"}
    if to == "assigned":
        kwargs["assignee"] = world.users["maintenance_technician"]
    if allowed:
        assert transition(action, to, world.users[user], **kwargs).status == to
    else:
        with pytest.raises(NotAllowed):
            transition(action, to, world.users[user], **kwargs)


def test_the_assignee_must_have_access_to_the_factory(
    new_action: Callable[..., MaintenanceAction], world: World
) -> None:
    action = new_action()
    for outsider in ("limited_operator", "other_manager"):  # Plant A only / another company
        with pytest.raises(WorkflowError, match="access"):
            transition(
                action,
                "assigned",
                world.users["production_supervisor"],
                assignee=world.users[outsider],
            )


def test_allowed_steps_lists_only_what_this_user_may_do(
    new_action: Callable[..., MaintenanceAction], world: World, api: ApiFactory
) -> None:
    action = new_action("in_progress")

    def steps(user: str) -> list[str]:
        body = api(world.users[user]).get(f"{URL}{action.id}/").json()
        return sorted(s["to"] for s in body["allowed_steps"])

    assert steps("maintenance_technician") == ["done", "waiting"]
    assert steps("production_supervisor") == ["cancelled"]
    assert steps("analyst") == []


def test_steps_are_announced_after_commit(
    new_action: Callable[..., MaintenanceAction],
    world: World,
    django_capture_on_commit_callbacks: Any,
) -> None:
    from asgiref.sync import async_to_sync
    from channels.layers import get_channel_layer

    from apps.live.broadcast import line_group
    from apps.live.tests.test_broadcast import _drain

    action = new_action("assigned")
    layer = get_channel_layer()
    channel = async_to_sync(layer.new_channel)()
    async_to_sync(layer.group_add)(line_group(action.line_id), channel)

    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        transition(action, "in_progress", world.users["maintenance_technician"])
    assert async_to_sync(_drain)(layer, channel) == []
    for callback in callbacks:
        callback()
    [message] = [
        m for m in async_to_sync(_drain)(layer, channel) if m["type"] == "maintenance_updated"
    ]
    assert (message["data"]["action_id"], message["data"]["status"]) == (action.id, "in_progress")
