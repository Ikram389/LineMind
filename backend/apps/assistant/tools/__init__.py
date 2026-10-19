"""The assistant's tools: read-only, each a thin wrapper around an existing service.

Kept small on purpose (13 tools, simple parameters, enums): smaller models pick tools
more reliably that way. The model never gets a tool that writes anything.
"""

from apps.assistant.tools.alerts import GetAlerts
from apps.assistant.tools.compare import ComparePeriods
from apps.assistant.tools.core import Tool
from apps.assistant.tools.downtime import GetDowntime, GetIncidents, GetRecurringStops
from apps.assistant.tools.maintenance import GetMaintenance
from apps.assistant.tools.production import (
    GetLineStatus,
    GetOee,
    GetProductionOrders,
    GetShifts,
    ListLines,
)
from apps.assistant.tools.quality import GetQuality
from apps.assistant.tools.time_ranges import ResolveTimeRange

TOOLS: tuple[Tool, ...] = (
    ListLines(),
    ResolveTimeRange(),
    GetShifts(),
    GetLineStatus(),
    GetOee(),
    GetDowntime(),
    GetRecurringStops(),
    GetIncidents(),
    GetQuality(),
    GetAlerts(),
    GetMaintenance(),
    GetProductionOrders(),
    ComparePeriods(),
)
BY_NAME: dict[str, Tool] = {tool.name: tool for tool in TOOLS}


def tool_specs() -> list[dict]:
    return [tool.spec() for tool in TOOLS]
