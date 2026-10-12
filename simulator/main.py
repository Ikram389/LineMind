"""LineMind factory simulator: command-line entry point.

Examples (from the repository root):
    docker compose run --rm simulator python main.py --scenario scenarios/labeler_jam.yaml \
        --mode accelerated --speed 60
    docker compose run --rm simulator python main.py --scenario scenarios/reference_1h.yaml \
        --mode backfill --start 2026-10-05T06:00:00Z
    docker compose run --rm simulator python main.py --scenario scenarios/normal_shift.yaml \
        --mode backfill --output file
"""

from __future__ import annotations

import argparse
import dataclasses
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

from event_queue import EventQueue
from report import format_report
from runner import Mode, RunError, resolve_start, run
from scenarios import ScenarioError, load_scenario, parse_duration, parse_start
from senders import EventSink, FileSink, HttpSink, SendError
from settings import load_settings
from simulation import Simulation

logger = logging.getLogger("simulator")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Simulate a bottling line and send its events.")
    parser.add_argument("--scenario", required=True, help="Path to a scenario YAML file")
    parser.add_argument("--mode", choices=[m.value for m in Mode], default=Mode.REALTIME.value)
    parser.add_argument(
        "--speed", type=float, default=60.0, help="Accelerated mode: simulated seconds per second"
    )
    parser.add_argument("--start", help="Backfill start, e.g. 2026-10-05T06:00:00Z")
    parser.add_argument("--duration", help="Override the scenario duration, e.g. 30m")
    parser.add_argument("--output", choices=["http", "file"], default="http")
    parser.add_argument("--file", help="Output file for --output file (JSON Lines)")
    parser.add_argument(
        "--drain-timeout",
        type=float,
        default=300.0,
        help="Seconds to keep retrying unsent events at the end",
    )
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=args.log_level.upper(), format="%(asctime)s %(levelname)s %(message)s"
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per request is too noisy
    settings = load_settings()

    try:
        scenario = load_scenario(args.scenario)
        if args.duration:
            duration = parse_duration(args.duration, "--duration", "command line")
            scenario = dataclasses.replace(scenario, duration=duration)
        mode = Mode(args.mode)
        start = resolve_start(
            mode,
            scenario.duration,
            now=datetime.now(UTC),
            speed=args.speed,
            start=parse_start(args.start, "--start") if args.start else None,
            scenario_start=scenario.start,
        )
    except (ScenarioError, RunError) as exc:
        logger.error("%s", exc)
        return 2

    simulation = Simulation(scenario, start=start)
    sink: EventSink
    if args.output == "file":
        path = Path(args.file or f"data/{scenario.name}-{start:%Y%m%dT%H%M%SZ}.jsonl")
        sink = FileSink(path)
        logger.info("Writing events to %s", path)
    else:
        if not settings.api_key:
            logger.error(
                "SIMULATOR_API_KEY is not set. Create a key with "
                "'docker compose exec backend python manage.py create_line_api_key <line_id> "
                '"Simulator"\' and put it in .env.'
            )
            return 2
        client = httpx.Client(base_url=settings.api_url, timeout=10.0)
        sink = HttpSink(client, settings.api_key, EventQueue(settings.queue_path))
        logger.info("Sending events to %s", settings.api_url)

    logger.info(
        "Running '%s' in %s mode from %s (%d s simulated)",
        scenario.name,
        mode.value,
        start.isoformat(),
        scenario.duration,
    )
    try:
        run(simulation, sink, mode, speed=args.speed)
        summary = sink.close(args.drain_timeout)
    except SendError as exc:
        logger.error("%s", exc)
        return 1
    except KeyboardInterrupt:
        logger.warning("Interrupted. Unsent events stay in the queue for the next run.")
        return 130

    print(format_report(simulation, summary, args.output))
    return 1 if summary.unsent else 0


if __name__ == "__main__":
    sys.exit(main())
