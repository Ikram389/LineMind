"""Shared helpers for downtime tests (fixtures are in conftest.py)."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from apps.organizations.models import Factory, Machine, ProductionLine
from apps.production.models import LineApiKey
from apps.production.services.api_keys import create_line_api_key

FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures"

BOTTLING_MACHINES = [
    ("M01", "Bottle feeder"),
    ("M02", "Rinser"),
    ("M03", "Filler"),
    ("M04", "Capper"),
    ("M05", "Labeler"),
    ("M06", "Packer"),
]


@dataclass
class Bottling:
    line: ProductionLine
    machines: dict[str, Machine]
    api_key: LineApiKey


def read_fixture(name: str) -> list[dict[str, Any]]:
    with (FIXTURES / f"{name}.jsonl").open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def create_bottling_line(factory: Factory, name: str) -> Bottling:
    """A six-machine bottling line (M01-M06, 6,000/h each) with its own API key."""
    line = ProductionLine.objects.create(factory=factory, name=name)
    machines = {
        external_id: Machine.objects.create(
            line=line,
            external_id=external_id,
            name=machine_name,
            machine_type=machine_name.lower(),
            position=index + 1,
            nominal_speed_per_hour=6000,
        )
        for index, (external_id, machine_name) in enumerate(BOTTLING_MACHINES)
    }
    api_key, _ = create_line_api_key(line, f"Fixture loader for {name}")
    return Bottling(line, machines, api_key)
