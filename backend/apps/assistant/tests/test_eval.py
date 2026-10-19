"""assistant_eval runs end to end on the fake provider and writes a readable report."""

import json
from collections.abc import Callable
from pathlib import Path

from django.core.management import call_command

from apps.assistant.eval import data
from apps.assistant.eval.questions import BY_ID, longest_jam
from apps.assistant.eval.report import render
from apps.assistant.eval.runner import Score
from apps.assistant.providers.fake import FakeProvider, FakeTurn
from apps.assistant.tools.core import iso


def test_the_evaluation_writes_a_report(
    db: None, tmp_path: Path, fake: Callable[..., FakeProvider]
) -> None:
    world = data.build(["Eval Line 2"])
    question = BY_ID["q4"]
    minutes_expected = longest_jam(world, question.now)[0][0]
    line = world.lines["Eval Line 2"]
    fake(
        FakeTurn(
            tool_calls=[
                (
                    "get_incidents",
                    {"line_id": line.pk, "start": "2026-10-11T23:00:00Z", "end": iso(question.now)},
                )
            ]
        ),
        FakeTurn(
            text=f"Today the longest line stop lasted {minutes_expected} min; "
            "its first observed stop was the Labeler [1]."
        ),
        FakeTurn(text="There is no data for another company's line."),
        model="openai/gpt-oss-120b",
    )
    call_command("assistant_eval", "--only", "q4,n1", "--pause", "0", "--output", str(tmp_path))

    report = next(tmp_path.glob("*.md")).read_text(encoding="utf-8")
    assert "| openai/gpt-oss-120b (development) | 2 | 1/1 (100%)" in report
    assert "## Production candidate: openai/gpt-oss-20b" in report
    assert "Not run. Add it with `--models openai/gpt-oss-120b,openai/gpt-oss-20b`" in report
    scores = json.loads(next(tmp_path.glob("*.json")).read_text(encoding="utf-8"))[
        "openai/gpt-oss-120b"
    ]
    q4, n1 = scores
    assert (q4["numbers_found"], q4["numbers_expected"], q4["texts_ok"], q4["sources_cited"]) == (
        1,
        1,
        True,
        True,
    )
    assert q4["tools"] == ["get_incidents"]
    assert n1["no_data_ok"] is True
    # Running it again changes nothing in the data (idempotent).
    assert data.build(["Eval Line 2"]).lines["Eval Line 2"].pk == line.pk


def test_the_report_highlights_where_the_production_candidate_differs() -> None:
    from datetime import UTC, datetime

    def s(model: str, question: str, found: int, invalid: int = 0) -> Score:
        return Score(
            question=question,
            model=model,
            language="en",
            status="ok",
            answer="…",
            expected=[1.0],
            numbers_found=found,
            numbers_expected=1,
            invalid_tool_calls=invalid,
        )

    scores = {
        "openai/gpt-oss-120b": [
            s("openai/gpt-oss-120b", "q1", 1),
            s("openai/gpt-oss-120b", "q3", 1),
        ],
        "openai/gpt-oss-20b": [
            s("openai/gpt-oss-20b", "q1", 1),
            s("openai/gpt-oss-20b", "q3", 0, invalid=2),
        ],
    }
    text = render(
        scores, "openai/gpt-oss-20b", "openai/gpt-oss-120b", datetime(2026, 10, 17, tzinfo=UTC)
    )
    assert "| openai/gpt-oss-20b **(production candidate)** |" in text
    assert "| q3 |" in text and "result 1/1 → 0/1" in text and "invalid tool calls 0 → 2" in text
    assert "| q1 |" not in text  # same result: not listed
