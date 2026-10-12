"""The short summary printed at the end of a run."""

from __future__ import annotations

from senders import SendSummary
from simulation import Simulation


def format_report(simulation: Simulation, summary: SendSummary, output: str) -> str:
    scenario = simulation.scenario
    end = simulation.time_at(simulation.tick * scenario.tick_seconds)
    lines = [
        f"Scenario '{scenario.name}' ({scenario.defect_mode} defects, seed {scenario.seed})",
        f"Simulated {simulation.start.isoformat()} -> {end.isoformat()}",
        "",
        f"{'Machine':<8}{'produced':>10}{'rejected':>10}{'good':>10}{'changes':>9}"
        "  time per state (s)",
    ]
    for machine in simulation.line.machines:
        stats = simulation.stats[machine.external_id]
        states = ", ".join(f"{s}={n}" for s, n in sorted(stats.seconds_in_state.items()))
        lines.append(
            f"{machine.external_id:<8}{stats.produced:>10}{stats.rejected:>10}{stats.good:>10}"
            f"{stats.state_changes:>9}  {states}"
        )

    lines.append("")
    if output == "file":
        lines.append(f"Events written: {summary.written}")
    else:
        lines.append(
            f"Events submitted: {summary.submitted} | created: {summary.created} | "
            f"duplicate: {summary.duplicate} | rejected: {summary.rejected} | "
            f"still queued: {summary.unsent}"
        )
        for reason, count in summary.rejection_reasons.most_common():
            lines.append(f"  rejected x{count}: {reason}")
    return "\n".join(lines)
