"""The evaluation report (Markdown), with the production candidate highlighted.

Production will most likely run a smaller local model (gpt-oss-20b): the summary shows it
as the "production candidate" and lists every question where it does worse or better than
the development model, so the assistant is judged by the model that will really run.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from statistics import mean

from apps.assistant.eval.questions import BY_ID
from apps.assistant.eval.runner import Score


def _pct(part: int, whole: int) -> str:
    return f"{part}/{whole} ({round(100 * part / whole)}%)" if whole else "–"


def summary_row(model: str, scores: Sequence[Score], label: str = "") -> str:
    data = [s for s in scores if not s.no_data]
    nodata = [s for s in scores if s.no_data]
    times = [s.duration_ms for s in scores if s.duration_ms]
    return (
        f"| {model}{label} | {len(scores)} "
        f"| {_pct(sum(s.numbers_ok and s.texts_ok for s in data), len(data))} "
        f"| {_pct(sum(s.language_ok for s in scores), len(scores))} "
        f"| {_pct(sum(bool(s.no_data_ok) for s in nodata), len(nodata))} "
        f"| {_pct(sum(s.sources_cited for s in data), len(data))} "
        f"| {sum(s.unverified for s in scores)} "
        f"| {sum(s.invalid_tool_calls for s in scores)} "
        f"| {sum(s.status != 'ok' for s in scores)} "
        f"| {round(mean(times) / 1000, 1) if times else '–'} s "
        f"| {sum(s.tokens for s in scores)} |"
    )


def _verdict(s: Score) -> str:
    if s.no_data:
        return "no data ✓" if s.no_data_ok else "no data ✗"
    numbers = f"{s.numbers_found}/{s.numbers_expected}"
    return f"{numbers}{'' if s.texts_ok else ' (text missing)'}"


def _ok(flag: bool) -> str:
    return "ok" if flag else "wrong"


def _differences(dev: dict[str, Score], prod: dict[str, Score]) -> list[str]:
    rows = []
    for qid in BY_ID:
        a, b = dev.get(qid), prod.get(qid)
        if a is None or b is None:
            continue
        changes = []
        if (a.numbers_ok and a.texts_ok) != (
            b.numbers_ok and b.texts_ok
        ) or a.no_data_ok != b.no_data_ok:
            changes.append(f"result {_verdict(a)} → {_verdict(b)}")
        if a.language_ok != b.language_ok:
            changes.append(f"language {_ok(a.language_ok)} → {_ok(b.language_ok)}")
        if a.unverified != b.unverified:
            changes.append(f"unverified numbers {a.unverified} → {b.unverified}")
        if a.invalid_tool_calls != b.invalid_tool_calls:
            changes.append(f"invalid tool calls {a.invalid_tool_calls} → {b.invalid_tool_calls}")
        if a.status != b.status:
            changes.append(f"status {a.status} → {b.status}")
        if changes:
            rows.append(f"| {qid} | {BY_ID[qid].text[:60]} | {'; '.join(changes)} |")
    return rows


def render(
    scores: dict[str, list[Score]],
    production_model: str,
    development_model: str,
    started: datetime,
) -> str:
    lines = [
        "# Assistant evaluation",
        "",
        f'Run {started:%Y-%m-%d %H:%M} UTC on the "Assistant Eval" data '
        "(simulator fixtures normal_shift_150m, labeler_jam, labeler_recurring_jams_24h + "
        "labeler_after_fix_24h). Expected numbers come from LineMind's services.",
        "",
        "## Summary",
        "",
        "| Model | Questions | Correct (numbers + text) | Language | No-data answered | "
        "Sources cited | Unverified numbers | Invalid tool calls | Failed | Avg time | Tokens |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for model, model_scores in scores.items():
        label = " **(production candidate)**" if model == production_model else ""
        if model == development_model:
            label = " (development)"
        lines.append(summary_row(model, model_scores, label))

    lines += ["", f"## Production candidate: {production_model}", ""]
    if production_model not in scores:
        lines.append(
            f"Not run. Add it with `--models {development_model},{production_model}` to see how "
            "the model that will run in production compares."
        )
    elif development_model not in scores:
        lines.append(f"The development model {development_model} was not run: nothing to compare.")
    else:
        dev = {s.question: s for s in scores[development_model]}
        prod = {s.question: s for s in scores[production_model]}
        rows = _differences(dev, prod)
        if rows:
            lines += [
                f"Questions where {production_model} differs from {development_model}:",
                "",
                "| Question | Text | Development → production candidate |",
                "|---|---|---|",
                *rows,
            ]
        else:
            lines.append(f"Same results as {development_model} on every question.")

    lines += ["", "## Answers", ""]
    for model, model_scores in scores.items():
        lines += [f"### {model}", ""]
        for s in model_scores:
            q = BY_ID[s.question]
            flags = [_verdict(s), f"lang {'ok' if s.language_ok else 'WRONG'}"]
            if s.unverified:
                flags.append(f"{s.unverified} unverified")
            if s.from_question:
                flags.append(f"{s.from_question} from question")
            if s.invalid_tool_calls:
                flags.append(f"{s.invalid_tool_calls} invalid calls")
            if s.error:
                flags.append(f"error: {s.error}")
            answer = s.answer.replace("\n", " ")
            lines += [
                f"**{s.question}** ({q.language}) {q.text}",
                "",
                f"- Result: {', '.join(flags)} · {s.duration_ms / 1000:.1f} s · {s.tokens} tokens",
                f"- Expected: {s.expected or '“no data available”'}",
                f"- Tools: {', '.join(s.tools) or 'none'}",
                f"- Answer: {answer[:700]}{'…' if len(answer) > 700 else ''}",
                "",
            ]
    return "\n".join(lines) + "\n"
