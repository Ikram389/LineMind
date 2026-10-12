"""Event types (docs/PRODUCT.md §13), machine states, and the mapping between them.

This is the only place that decides what an incoming event means.
"""

from django.db import models


class MachineState(models.TextChoices):
    RUNNING = "running", "Running"
    STOPPED = "stopped", "Stopped"
    BLOCKED = "blocked", "Blocked"
    STARVED = "starved", "Starved"
    PLANNED_STOP = "planned_stop", "Planned stop"
    UNKNOWN = "unknown", "Unknown"


class EventType(models.TextChoices):
    MACHINE_STARTED = "machine_started"
    MACHINE_STOPPED = "machine_stopped"
    MACHINE_BLOCKED = "machine_blocked"
    MACHINE_STARVED = "machine_starved"
    PLANNED_STOP_STARTED = "planned_stop_started"
    PLANNED_STOP_ENDED = "planned_stop_ended"
    PRODUCTION_COUNT_UPDATED = "production_count_updated"
    QUALITY_DEFECT_DETECTED = "quality_defect_detected"
    SENSOR_DISCONNECTED = "sensor_disconnected"
    SENSOR_RECONNECTED = "sensor_reconnected"


# Event types that record a machine state transition (-> MachineStateEvent).
# sensor_reconnected is deliberately absent: it does not prove the machine is
# running, so the state stays "unknown" until a real state event arrives.
EVENT_TYPE_TO_STATE: dict[str, MachineState] = {
    EventType.MACHINE_STARTED: MachineState.RUNNING,
    EventType.MACHINE_STOPPED: MachineState.STOPPED,
    EventType.MACHINE_BLOCKED: MachineState.BLOCKED,
    EventType.MACHINE_STARVED: MachineState.STARVED,
    EventType.PLANNED_STOP_STARTED: MachineState.PLANNED_STOP,
    EventType.PLANNED_STOP_ENDED: MachineState.RUNNING,
    EventType.SENSOR_DISCONNECTED: MachineState.UNKNOWN,
}

# Event types that record a production count (-> ProductionEvent).
PRODUCTION_EVENT_TYPES: frozenset[str] = frozenset({EventType.PRODUCTION_COUNT_UPDATED})

# All other types (sensor_reconnected, quality_defect_detected) are stored only
# as IngestedEvent for now. quality_defect_detected is processed in build step 9.
