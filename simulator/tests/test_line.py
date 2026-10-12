"""Line physics: buffers, derived states, speed arithmetic and unit conservation."""

from __future__ import annotations

from fractions import Fraction

from factory import Condition, ExactDefects, Line
from machines import MachineState
from scenarios import MachineConfig, load_line_config, load_scenario
from simulation import Simulation
from tests.helpers import CONFIG_DIR, SCENARIOS_DIR, make_scenario, state_events

RUNNING = MachineState.RUNNING


def record(sim: Simulation) -> list[dict[str, object]]:
    """Run to the end, recording each tick's states and buffer levels after the tick."""
    ticks = []
    while not sim.finished:
        sim.step()
        ticks.append(
            {
                "states": {m.external_id: m.state for m in sim.line.machines},
                "levels": {b.name: b.level for b in sim.line.buffers},
            }
        )
    return ticks


def first_tick(ticks: list[dict[str, object]], machine: str, state: MachineState) -> int:
    return next(i for i, t in enumerate(ticks) if t["states"][machine] == state)


def test_labeler_stop_blocks_capper_only_when_buffer_full_and_starves_packer_when_empty() -> None:
    fault_at, fault_len = 60, 60
    sim = Simulation(
        make_scenario(
            duration=300,
            faults=[{"machine": "M05", "at": fault_at, "duration": fault_len}],
        )
    )
    ticks = record(sim)

    blocked = first_tick(ticks, "M04", MachineState.BLOCKED)
    starved = first_tick(ticks, "M06", MachineState.STARVED)

    # Capper: blocked exactly when the buffer to the labeler had become full, not before.
    assert blocked > fault_at
    assert ticks[blocked - 1]["levels"]["M04-M05"] == 50
    assert ticks[blocked - 2]["levels"]["M04-M05"] < 50
    assert all(ticks[i]["states"]["M04"] == RUNNING for i in range(fault_at, blocked))

    # Packer: starved exactly when its input buffer had become empty, not before.
    assert starved > fault_at
    assert ticks[starved - 1]["levels"]["M05-M06"] == 0
    assert ticks[starved - 2]["levels"]["M05-M06"] > 0
    assert all(ticks[i]["states"]["M06"] == RUNNING for i in range(fault_at, starved))

    # Both stay in that state until the fault ends, then recover by themselves.
    fault_end = fault_at + fault_len
    assert all(ticks[i]["states"]["M04"] == MachineState.BLOCKED for i in range(blocked, fault_end))
    assert all(ticks[i]["states"]["M06"] == MachineState.STARVED for i in range(starved, fault_end))
    assert ticks[fault_end]["states"]["M04"] == RUNNING
    assert ticks[fault_end + 1]["states"]["M06"] == RUNNING
    for tick in ticks[fault_end + 2 :]:
        assert set(tick["states"].values()) == {RUNNING}


def test_labeler_jam_scenario_matches_product_timeline() -> None:
    events = state_events(Simulation(load_scenario(SCENARIOS_DIR / "labeler_jam.yaml")).run_all())
    firsts = {}
    for event in events:
        key = (event.machine_external_id, event.event_type)
        if event.timestamp.minute >= 5 and key not in firsts:
            firsts[key] = event.timestamp.strftime("%H:%M:%S")

    assert firsts[("M05", "machine_stopped")] == "10:05:00"
    assert firsts[("M04", "machine_blocked")] == "10:05:03"
    assert firsts[("M06", "machine_starved")] == "10:05:08"
    assert firsts[("M03", "machine_blocked")] == "10:05:40"
    assert firsts[("M05", "machine_started")] == "10:06:30"


def test_feeder_never_starved_and_packer_never_blocked() -> None:
    sim = Simulation(
        make_scenario(
            duration=900,
            faults=[
                {"machine": "M01", "at": 60, "duration": 120},
                # Long enough for all five buffers to fill and block the feeder.
                {"machine": "M06", "at": 300, "duration": 400},
            ],
        )
    )
    ticks = record(sim)

    assert MachineState.STARVED not in {t["states"]["M01"] for t in ticks}
    assert MachineState.BLOCKED not in {t["states"]["M06"] for t in ticks}
    assert MachineState.STARVED in {t["states"]["M06"] for t in ticks}  # sanity: cascade happened
    assert MachineState.BLOCKED in {t["states"]["M01"] for t in ticks}


def test_units_are_conserved() -> None:
    sim = Simulation(
        make_scenario(
            duration=1800,
            defect_mode="random",
            faults=[{"machine": "M04", "at": 100, "duration": 200}],
            defects=[{"machine": "M03", "rates": {"Q01": 0.05}}],
        )
    )
    initial_in_buffers = sum(b.level for b in sim.line.buffers)
    sim.run_all()

    feeder = sim.line.machine("M01")
    in_buffers = sum(b.level for b in sim.line.buffers)
    removed = sum(m.rejected for m in sim.line.machines)
    shipped = sim.line.machine("M06").good
    assert feeder.count + initial_in_buffers == in_buffers + removed + shipped


def test_speed_arithmetic_is_exact() -> None:
    sim = Simulation(make_scenario(duration=3600))
    sim.run_all()

    assert {m.count for m in sim.line.machines} == {6000}


def test_slow_machine_does_not_flicker() -> None:
    line = load_line_config(CONFIG_DIR / "bottling_line_1.yaml")
    slow = Line(line)
    slow.machines[2].config = MachineConfig("M03", "Filler", "filler", speed_per_hour=1800)

    states = []
    for _ in range(120):
        slow.tick({}, 1)
        states.append(slow.machine("M03").state)

    assert set(states) == {RUNNING}  # 0.5 units/s: idle ticks are not "starved" or "blocked"
    assert slow.machine("M03").count == 60


def test_faulted_machine_builds_no_credit() -> None:
    line = Line(load_line_config(CONFIG_DIR / "bottling_line_1.yaml"))
    for _ in range(30):
        line.tick({"M01": Condition("fault", "E-1")}, 1)

    feeder = line.machine("M01")
    assert feeder.count == 0
    assert feeder.credit == 0
    assert feeder.state == MachineState.STOPPED
    assert feeder.alarm_code == "E-1"


def test_exact_defects_round_half_up_per_code() -> None:
    line = Line(
        load_line_config(CONFIG_DIR / "bottling_line_1.yaml"),
        ExactDefects({"M06": {"Q02": Fraction(1, 50), "Q04": Fraction(1, 100)}}),
    )
    for _ in range(3600):
        line.tick({}, 1)

    packer = line.machine("M06")
    assert packer.count == 6000
    assert dict(packer.rejected_by_code) == {"Q02": 120, "Q04": 60}
