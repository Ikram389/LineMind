from collections.abc import Callable
from datetime import time
from typing import Any

import pytest

from apps.maintenance.models import MaintenanceAction
from apps.maintenance.services.actions import create_action, update_action
from apps.maintenance.services.workflow import transition
from apps.production.models import Shift
from tests.helpers import World
from tests.lines import Bottling


@pytest.fixture
def all_day_shift(bottling: Bottling) -> Shift:
    """One 24-hour shift every day (factory B is in UTC); no gaps in sparse test data."""
    factory = bottling.line.factory
    factory.stale_after_seconds = 24 * 3600
    factory.save()
    return Shift.objects.create(
        factory=factory, name="All day", start_time=time(0), end_time=time(0)
    )


@pytest.fixture
def new_action(world: World, bottling: Bottling) -> Callable[..., MaintenanceAction]:
    """new_action(status="requested", **fields): an action on the Labeler, moved through the
    workflow to `status` by the right people."""

    def _new(
        status: str = "requested", links: list[dict[str, Any]] | None = None, **fields: Any
    ) -> MaintenanceAction:
        defaults: dict[str, Any] = {"title": "Labeler jams", "problem": "E-204 every hour"}
        defaults.update(fields)
        planning = {k: defaults.pop(k) for k in ("priority", "due_date") if k in defaults}
        action = create_action(
            world.users["machine_operator"], bottling.machines["M05"], defaults, links or []
        )
        supervisor = world.users["production_supervisor"]
        if planning:  # set by a supervisor, as in real use
            action = update_action(action, supervisor, planning)
        technician = world.users["maintenance_technician"]
        path = ["assigned", "in_progress", "done", "verified"]
        for step in path[: path.index(status) + 1] if status in path else []:
            if step == "assigned":
                transition(action, "assigned", supervisor, assignee=technician)
            elif step == "verified":
                from apps.maintenance.services.workflow import verify

                verify(action, "effective", "", supervisor)
            else:
                transition(action, step, technician)
        if status in ("waiting", "cancelled"):
            if status == "waiting":
                transition(action, "assigned", supervisor, assignee=technician)
                transition(action, "in_progress", technician)
                transition(action, "waiting", technician, note="Waiting for a part")
            else:
                transition(action, "cancelled", supervisor, note="Duplicate")
        action.refresh_from_db()
        return action

    return _new
