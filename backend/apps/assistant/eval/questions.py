"""The evaluation questions and how each answer is judged.

Expected numbers are computed from the same services as the screens, at run time (never
typed in by hand). An expectation may list alternatives (a model may reasonably answer
"label defects" with all defects, or with one label defect type): the best one counts.
Each question fixes its own "now", so "this week" always means the same range.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from apps.analytics.services.report import oee_report
from apps.assistant.eval.data import CHANGEOVER, EvalWorld
from apps.assistant.tools.core import minutes, pct
from apps.assistant.tools.time_ranges import resolve_range
from apps.downtime.models import LineStopIncident
from apps.downtime.services.analysis import (
    AnalysisFilters,
    pareto,
    recurring,
    select_entries,
    summary,
)
from apps.downtime.services.durations import duration_seconds
from apps.maintenance.services.effectiveness import effectiveness
from apps.quality.services.metrics import QualityFilters
from apps.quality.services.metrics import summary as quality_summary

Expect = Callable[[EvalWorld, datetime], list[list[float]]]


@dataclass(frozen=True)
class Question:
    id: str
    language: str
    text: str
    now: datetime
    line: str  # the line the question is about (its data is loaded for the run)
    expect: Expect | None = None  # alternatives of expected numbers; None: "no data"
    texts: tuple[str, ...] = ()  # words the answer must contain (e.g. a machine name)
    tags: tuple[str, ...] = field(default_factory=tuple)

    @property
    def no_data(self) -> bool:
        return self.expect is None


def at(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


# --- Expectations (services, never hand-typed) -----------------------------------------


def _range(world: EvalWorld, now: datetime, phrase: str, **kw: Any) -> tuple[datetime, datetime]:
    r = resolve_range(world.factory, now, phrase, **kw)
    return r.start, r.end


def top_machine_downtime(world: EvalWorld, now: datetime) -> list[list[float]]:
    line = world.lines["Eval Line 3"]
    start, end = _range(world, now, "this_week")
    f = AnalysisFilters(start=start, end=end, now=now)
    groups = pareto(select_entries([line], f), "machine", "line")["groups"]
    return [[minutes(groups[0]["total_seconds"])]] if groups else [[]]


def label_defects_around_changeover(world: EvalWorld, now: datetime) -> list[list[float]]:
    line = world.lines["Eval Line 1"]
    before = (datetime(2026, 10, 5, 5, 0, tzinfo=UTC), CHANGEOVER)
    after = (CHANGEOVER, datetime(2026, 10, 5, 9, 0, tzinfo=UTC))
    options = []
    for code in (None, "Q02", "Q03"):
        options.append(
            [
                float(
                    quality_summary([line], QualityFilters(start=s, end=e, defect_type=code))[
                        "defects"
                    ]
                )
                for s, e in (before, after)
            ]
        )
    return options


def morning_oee(world: EvalWorld, now: datetime) -> list[list[float]]:
    start, end = _range(world, now, "shift_on_date", day=date(2026, 10, 5), shift_name="Morning")
    total = oee_report(world.lines["Eval Line 1"], start, end, None, now)["total"]
    return [[total["oee"]["percent"]]]


def longest_jam(world: EvalWorld, now: datetime) -> list[list[float]]:
    incidents = LineStopIncident.objects.filter(line=world.lines["Eval Line 2"])
    longest = max(incidents, key=lambda i: duration_seconds(i.started_at, i.ended_at, now))
    return [[minutes(duration_seconds(longest.started_at, longest.ended_at, now))]]


def labeler_fix(world: EvalWorld, now: datetime) -> list[list[float]]:
    assert world.action is not None
    result = effectiveness(world.action, now=now)
    return [[result["before"]["occurrences_per_10h"], result["after"]["occurrences_per_10h"]]]


def unreviewed_defects(world: EvalWorld, now: datetime) -> list[list[float]]:
    start, end = _range(world, now, "date", day=date(2026, 10, 5))
    return [
        [
            float(
                quality_summary([world.lines["Eval Line 1"]], QualityFilters(start=start, end=end))[
                    "unreviewed"
                ]
            )
        ]
    ]


def stops_two_days(world: EvalWorld, now: datetime) -> list[list[float]]:
    values = []
    for day in (date(2026, 9, 29), date(2026, 9, 30)):
        start, end = _range(world, now, "date", day=day)
        f = AnalysisFilters(start=start, end=end, now=now)
        values.append(
            float(summary(select_entries([world.lines["Eval Line 3"]], f), "line")["stops"])
        )
    return [values]


def labeler_recurring(world: EvalWorld, now: datetime) -> list[list[float]]:
    start, end = _range(world, now, "this_week")
    items = recurring([world.lines["Eval Line 3"]], AnalysisFilters(start=start, end=end, now=now))[
        "items"
    ]
    labeler = [i for i in items if i["machine"]["name"] == "Labeler"]
    return [[float(labeler[0]["count"])]] if labeler else [[]]


def defect_rate(world: EvalWorld, now: datetime) -> list[list[float]]:
    start, end = _range(world, now, "date", day=date(2026, 10, 5))
    rate = quality_summary([world.lines["Eval Line 1"]], QualityFilters(start=start, end=end))[
        "defect_rate"
    ]
    return [[pct(rate, 2) or 0.0]]


# --- The question set ----------------------------------------------------------------

THU_1_OCT = at("2026-10-01T06:00:00")
TUE_6_OCT = at("2026-10-06T08:00:00")
MON_12_OCT = at("2026-10-12T12:00:00")
FRI_2_OCT = at("2026-10-02T06:00:00")

QUESTIONS: tuple[Question, ...] = (
    # The five examples of docs/PRODUCT.md §8
    Question(
        "q1",
        "en",
        "Which machine caused the most downtime this week on Eval Line 3?",
        THU_1_OCT,
        "Eval Line 3",
        top_machine_downtime,
        ("Labeler",),
        ("product",),
    ),
    Question(
        "q2",
        "en",
        "Did label defects increase after the last changeover on Eval Line 1? "
        "Look at 5 October 2026.",
        TUE_6_OCT,
        "Eval Line 1",
        label_defects_around_changeover,
        tags=("product",),
    ),
    Question(
        "q3",
        "en",
        "What was the OEE of Eval Line 1 during the Morning shift on 5 October "
        "2026, and what lost the most time?",
        TUE_6_OCT,
        "Eval Line 1",
        morning_oee,
        tags=("product",),
    ),
    Question(
        "q4",
        "en",
        "What was the first observed stop of the longest line stop on Eval Line 2 today?",
        MON_12_OCT,
        "Eval Line 2",
        longest_jam,
        ("Labeler",),
        ("product",),
    ),
    Question(
        "q5",
        "en",
        "Did the labeler maintenance action reduce the stops on Eval Line 3?",
        FRI_2_OCT,
        "Eval Line 3",
        labeler_fix,
        tags=("product",),
    ),
    # More questions in English
    Question(
        "q6",
        "en",
        "How many defects on Eval Line 1 are not reviewed yet for 5 October 2026?",
        TUE_6_OCT,
        "Eval Line 1",
        unreviewed_defects,
    ),
    Question(
        "q7",
        "en",
        "Compare the number of line stops on Eval Line 3 on 29 September 2026 "
        "with 30 September 2026.",
        FRI_2_OCT,
        "Eval Line 3",
        stops_two_days,
    ),
    Question(
        "q8",
        "en",
        "Which stops recur on the labeler of Eval Line 3 this week?",
        THU_1_OCT,
        "Eval Line 3",
        labeler_recurring,
        ("Labeler",),
    ),
    Question(
        "q9",
        "en",
        "What was the defect rate on Eval Line 1 on 5 October 2026?",
        TUE_6_OCT,
        "Eval Line 1",
        defect_rate,
    ),
    # French
    Question(
        "fr1",
        "fr",
        "Quelle machine a causé le plus de temps d'arrêt cette semaine sur Eval Line 3 ?",
        THU_1_OCT,
        "Eval Line 3",
        top_machine_downtime,
        ("Labeler",),
        ("translation",),
    ),
    Question(
        "fr3",
        "fr",
        "Quel était le TRS (OEE) de Eval Line 1 pendant l'équipe Morning du 5 octobre 2026 ?",
        TUE_6_OCT,
        "Eval Line 1",
        morning_oee,
        tags=("translation",),
    ),
    Question(
        "fr5",
        "fr",
        "L'action de maintenance sur l'étiqueteuse (Labeler) a-t-elle réduit les arrêts "
        "sur Eval Line 3 ?",
        FRI_2_OCT,
        "Eval Line 3",
        labeler_fix,
        tags=("translation",),
    ),
    # Arabic
    Question(
        "ar1",
        "ar",
        "ما الآلة التي تسببت في أكبر وقت توقف هذا الأسبوع على Eval Line 3؟",
        THU_1_OCT,
        "Eval Line 3",
        top_machine_downtime,
        ("Labeler",),
        ("translation",),
    ),
    Question(
        "ar3",
        "ar",
        "ما هي الفعالية الإجمالية (OEE) لـ Eval Line 1 خلال وردية Morning يوم 5 أكتوبر 2026؟",
        TUE_6_OCT,
        "Eval Line 1",
        morning_oee,
        tags=("translation",),
    ),
    Question(
        "ar5",
        "ar",
        "هل قلّل إجراء الصيانة على آلة الملصقات (Labeler) من التوقفات على Eval Line 3؟",
        FRI_2_OCT,
        "Eval Line 3",
        labeler_fix,
        tags=("translation",),
    ),
    # Should be answered "no data available"
    Question(
        "n1",
        "en",
        "What was the OEE of Other Company's line yesterday?",
        MON_12_OCT,
        "Eval Line 2",
        tags=("no_data",),
    ),
    Question(
        "n2",
        "en",
        "How much downtime did Line 7 have last week?",
        MON_12_OCT,
        "Eval Line 2",
        tags=("no_data",),
    ),
    Question(
        "n3",
        "en",
        "What was the OEE of Eval Line 2 in March 2019?",
        MON_12_OCT,
        "Eval Line 2",
        tags=("no_data",),
    ),
    Question(
        "n4",
        "en",
        "What is the temperature of the filler on Eval Line 2?",
        MON_12_OCT,
        "Eval Line 2",
        tags=("no_data",),
    ),
)
BY_ID = {q.id: q for q in QUESTIONS}
