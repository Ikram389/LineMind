"""The fixes from the first live run: answer language, citations, unchecked answers,
maintenance effectiveness, missing-data minutes, "not calculable" values, and the evaluation
runner's handling of rate limits."""

import json
from collections.abc import Callable
from datetime import UTC, datetime, time, timedelta
from typing import Any

import pytest

from apps.analytics.services.report import oee_report
from apps.assistant.eval import data as eval_data
from apps.assistant.eval import runner
from apps.assistant.eval.questions import BY_ID
from apps.assistant.models import Conversation, Message, MessageRole
from apps.assistant.providers.errors import ProviderBusy
from apps.assistant.providers.fake import FakeProvider, FakeTurn
from apps.assistant.services.answer_text import clean_answer
from apps.assistant.services.numbers import check_numbers
from apps.assistant.services.orchestrator import REMINDER, ask
from apps.assistant.services.prompt import build_system_prompt
from apps.assistant.tools.core import ToolContext, iso, minutes
from apps.downtime.services.analysis import AnalysisFilters, select_entries, summary
from apps.maintenance.models import MaintenanceAction
from apps.maintenance.services.actions import create_action
from apps.production.models import Shift
from tests.helpers import World
from tests.lines import Bottling

from .conftest import AFTER_JAM, JAM_END, JAM_START

Fake = Callable[..., FakeProvider]
NewConversation = Callable[..., Conversation]


def run(conversation: Conversation, question: str) -> list[tuple[str, dict[str, Any]]]:
    return list(ask(conversation, question, conversation.user, now=AFTER_JAM))


def jam_conversation(conversation: NewConversation, bottling: Bottling) -> Conversation:
    """Asked from the Downtime screen showing the jam (its range is LineMind's: "screen")."""
    return conversation(line=bottling.line, context_start=JAM_START, context_end=JAM_END)


def jam_total(bottling: Bottling) -> float:
    s = summary(
        select_entries(
            [bottling.line], AnalysisFilters(start=JAM_START, end=JAM_END, now=AFTER_JAM)
        ),
        "line",
    )
    return minutes(s["total_seconds"])  # type: ignore[return-value]


SCREEN = {"range_id": "screen"}


# --- #2 + A: the rewrite in the question's language is what gets checked and stored -----


def test_a_wrong_language_answer_is_rewritten_and_the_rewrite_is_checked(
    bottling: Bottling, load: Callable[..., None], fake: Fake, conversation: NewConversation
) -> None:
    load("labeler_jam")
    total = jam_total(bottling)
    provider = fake(
        FakeTurn(tool_calls=[("get_downtime", {"line_id": bottling.line.pk, **SCREEN})]),
        FakeTurn(text=f"The line lost {total} min [1]."),  # English, to a French question
        FakeTurn(
            text=f"La ligne a perdu {total} min et 57 bouteilles【1】."
        ),  # adds an invented number
    )
    events = run(
        jam_conversation(conversation, bottling), "Combien de temps d'arrêt sur la ligne ?"
    )

    rewrite_request = provider.requests[2]
    assert rewrite_request["tools"] == []  # a rewrite cannot call tools
    assert "Rewrite your whole answer in French" in rewrite_request["messages"][-1]["content"]
    names = [name for name, _ in events]
    assert names.count("text_reset") >= 1 and names[-1] == "final"
    answer = events[-1][1]
    assert (
        answer["content"] == f"La ligne a perdu {total} min et 57 bouteilles[1]."
    )  # cleaned rewrite
    flagged = [i["text"] for i in answer["number_check"]["items"] if i["status"] == "unverified"]
    assert flagged == ["57"]  # the check ran on the rewrite, not the first answer


def test_no_rewrite_when_the_language_is_right(
    bottling: Bottling, load: Callable[..., None], fake: Fake, conversation: NewConversation
) -> None:
    load("labeler_jam")
    total = jam_total(bottling)
    provider = fake(
        FakeTurn(tool_calls=[("get_downtime", {"line_id": bottling.line.pk, **SCREEN})]),
        FakeTurn(text=f"La ligne a perdu {total} min [1]."),
    )
    run(jam_conversation(conversation, bottling), "Combien de temps d'arrêt sur la ligne ?")
    assert len(provider.requests) == 2


# --- #3: the "first observed stop" term in the question's language only ------------------


@pytest.mark.parametrize(
    "language, present, absent",
    [
        ("en", "first observed stop", "premier arrêt observé"),
        ("fr", "premier arrêt observé", "أول توقف"),
        ("ar", "أول توقف مُلاحَظ", "premier arrêt observé"),
    ],
)
def test_the_prompt_uses_the_question_language_only(
    world: World, bottling: Bottling, language: str, present: str, absent: str
) -> None:
    user = world.users["production_supervisor"]
    ctx = ToolContext(user, user.membership.organization, AFTER_JAM)
    system, _ = build_system_prompt(ctx, [bottling.line], bottling.line, None, language)
    assert present in system and absent not in system
    assert system.rstrip().endswith(
        "Write the whole answer in "
        + {"en": "English", "fr": "French", "ar": "Arabic"}[language]
        + "."
    )
    assert "call get_maintenance with its action_id" in system  # #5


# --- #4: citations in any format become [n]; ⟦ ⟧ never reaches an answer -----------------


def test_citation_formats_are_cleaned() -> None:
    raw = "OEE 78.4 %【2】, downtime【3†L1-L3】 ⟦1⟧ for ⟦This week⟧."
    assert clean_answer(raw) == "OEE 78.4 %[2], downtime[3] [1] for This week."


def test_a_cited_answer_has_no_false_unverified_numbers(
    bottling: Bottling, load: Callable[..., None], fake: Fake, conversation: NewConversation
) -> None:
    load("labeler_jam")
    total = jam_total(bottling)
    fake(
        FakeTurn(tool_calls=[("get_downtime", {"line_id": bottling.line.pk, **SCREEN})]),
        FakeTurn(text=f"The line lost {total} min【3】【4†L1】."),
    )
    answer = run(jam_conversation(conversation, bottling), "Downtime?")[-1][1]
    assert answer["content"] == f"The line lost {total} min[3][4]."
    assert answer["number_check"]["unverified"] == 0


# --- #6 + B: no data checked → one reminder → otherwise marked "unchecked" -----------------


def test_an_answer_without_tools_gets_one_reminder_then_is_marked_unchecked(
    fake: Fake, conversation: NewConversation
) -> None:
    provider = fake(
        FakeTurn(text="There is no data for that line."),
        FakeTurn(text="No data is available for that line."),
    )
    conv = conversation()
    answer = run(conv, "What was the OEE of Line 7 yesterday?")[-1][1]
    assert provider.requests[1]["messages"][-1]["content"] == REMINDER
    assert len(provider.requests) == 2  # one reminder only
    assert answer["unchecked"] is True
    assert answer["content"] == "No data is available for that line."
    stored = Message.objects.get(pk=answer["id"])
    assert stored.unchecked is True


def test_an_answer_that_checks_after_the_reminder_is_not_marked(
    bottling: Bottling, fake: Fake, conversation: NewConversation
) -> None:
    fake(
        FakeTurn(text="Line 7 does not exist."),
        FakeTurn(tool_calls=[("list_lines", {})]),
        FakeTurn(text="Line 7 is not one of your lines [1]."),
    )
    answer = run(conversation(), "What was the OEE of Line 7 yesterday?")[-1][1]
    assert answer["unchecked"] is False
    assert [c["name"] for c in answer["tool_calls"]] == ["list_lines"]


# --- #5: completed maintenance actions are found by default --------------------------------


def test_completed_actions_are_listed_by_default(world: World, bottling: Bottling) -> None:
    action = create_action(
        world.users["machine_operator"], bottling.machines["M05"], {"title": "Labeler jams"}, []
    )
    MaintenanceAction.objects.filter(pk=action.pk).update(status="done")  # test setup
    user = world.users["production_supervisor"]
    ctx = ToolContext(user, user.membership.organization, AFTER_JAM)
    from apps.assistant.providers.base import RawToolCall
    from apps.assistant.services.tool_runner import run_tool

    outcome = run_tool(
        RawToolCall("t", "get_maintenance", json.dumps({"line_id": bottling.line.pk})), ctx
    )
    assert outcome.result is not None
    assert [a["action_id"] for a in outcome.result.data["actions"]] == [action.pk]


# --- #7 and #8: missing-data minutes, and "not calculable" instead of null -----------------


@pytest.fixture
def morning_only(bottling: Bottling) -> Shift:
    return Shift.objects.create(
        factory=bottling.line.factory, name="Morning", start_time=time(6), end_time=time(14)
    )


def oee_call(world: World, bottling: Bottling, start: datetime, end: datetime) -> Any:
    from apps.assistant.providers.base import RawToolCall
    from apps.assistant.services.tool_runner import run_tool

    user = world.users["production_supervisor"]
    ctx = ToolContext(user, user.membership.organization, AFTER_JAM)
    ctx.ranges.add(start, end, "test range")
    args = {"line_id": bottling.line.pk, "start": iso(start), "end": iso(end)}
    outcome = run_tool(RawToolCall("t", "get_oee", json.dumps(args)), ctx)
    assert outcome.valid and outcome.result is not None, outcome.error
    return outcome.result


def test_oee_reports_minutes_without_machine_data(
    world: World, bottling: Bottling, load: Callable[..., None], morning_only: Shift
) -> None:
    load("labeler_jam")  # data from 10:00 only
    start = JAM_START - timedelta(hours=1)
    result = oee_call(world, bottling, start, JAM_END)
    expected = oee_report(bottling.line, start, JAM_END, None, AFTER_JAM)["total"]["inputs"]
    assert result.data["no_data_minutes"] == minutes(expected["no_data_seconds"]) >= 59
    assert result.data["no_data_counted_as_downtime"] is True  # the default setting
    assert any("had no data from the machines" in w for w in result.warnings)


def test_values_that_cannot_be_calculated_say_why(
    world: World, bottling: Bottling, morning_only: Shift
) -> None:
    night = datetime(2026, 10, 12, 2, 0, tzinfo=UTC)  # outside the Morning shift
    result = oee_call(world, bottling, night, night + timedelta(hours=1))
    assert isinstance(result.data["oee_percent"], str)
    assert result.data["oee_percent"].startswith("not calculable: ")
    assert None not in (result.data["availability_percent"], result.data["quality_percent"])


# --- #9: line names are LineMind context; recurring stops use clear field names -----------


def test_line_names_from_the_prompt_are_trusted() -> None:
    check = check_numbers(
        "Eval Line 1 and Eval Line 2.", {}, "", {"line_names": ["Eval Line 1", "Eval Line 2"]}
    )
    assert check["unverified"] == 0


def test_recurring_stops_say_occurrence_not_stop(
    world: World, bottling: Bottling, send: Any
) -> None:
    from apps.assistant.providers.base import RawToolCall
    from apps.assistant.services.tool_runner import run_tool

    factory = bottling.line.factory
    factory.stale_after_seconds = 24 * 3600  # sparse hand-made events
    factory.save()
    start = datetime(2026, 10, 12, 6, 0, tzinfo=UTC)
    for minute in (0, 10, 20):
        send("M05", "machine_stopped", start + timedelta(minutes=minute), alarm_code="E-204")
        send("M05", "machine_started", start + timedelta(minutes=minute + 3))
    user = world.users["production_supervisor"]
    ctx = ToolContext(user, user.membership.organization, AFTER_JAM)
    ctx.ranges.add(start, start + timedelta(hours=1), "test range")
    args = {
        "line_id": bottling.line.pk,
        "start": iso(start),
        "end": iso(start + timedelta(hours=1)),
    }
    outcome = run_tool(RawToolCall("t", "get_recurring_stops", json.dumps(args)), ctx)
    item = outcome.result.data["recurring"][0]  # type: ignore[union-attr]
    assert {"first_occurrence", "last_occurrence"} <= set(item) and "first" not in item


# --- #10: the evaluation runner and rate limits --------------------------------------------


@pytest.fixture
def eval_world(db: None) -> eval_data.EvalWorld:
    return eval_data.build([])  # no events needed for the no-data questions


NO_DATA = [BY_ID[q] for q in ("n1", "n2", "n3", "n4")]


def test_a_busy_question_is_retried_once_then_marked_not_run(eval_world: Any) -> None:
    busy = FakeTurn(error=ProviderBusy(retry_after=30))
    provider = FakeProvider([busy, busy, FakeTurn(text="No data."), FakeTurn(text="No data.")])
    sleeps: list[float] = []
    messages: list[str] = []
    scores = runner.run(NO_DATA[:2], eval_world, provider, 0, sleeps.append, messages.append)
    assert scores[0].status == runner.NOT_RUN  # rate limited: not counted as a model failure
    assert scores[1].status == "ok"
    assert any("retrying it once" in m for m in messages)


def test_three_rate_limited_questions_stop_the_model(eval_world: Any) -> None:
    busy = FakeTurn(error=ProviderBusy())
    provider = FakeProvider([busy] * 6)
    messages: list[str] = []
    scores = runner.run(NO_DATA, eval_world, provider, 0, lambda s: None, messages.append)
    assert [s.status for s in scores] == [runner.NOT_RUN] * 4
    assert len(provider.requests) == 6  # 3 questions × (ask + retry); the 4th is not asked
    assert any("Stopping this model" in m and "--resume" in m for m in messages)


def test_waits_are_capped_and_explained(eval_world: Any) -> None:
    provider = FakeProvider([FakeTurn(text="No data."), FakeTurn(text="No data.")])
    provider.remaining_tokens = 100  # type: ignore[attr-defined]
    provider.reset_tokens_seconds = 3716.0  # type: ignore[attr-defined]
    sleeps: list[float] = []
    messages: list[str] = []
    runner.run(NO_DATA[:1], eval_world, provider, 0, sleeps.append, messages.append)
    assert max(sleeps) == runner.MAX_WAIT_SECONDS == 120.0  # never an hour
    assert any(m.startswith("Waiting 120 s: only 100 tokens left") for m in messages)


def test_resume_keeps_answers_and_runs_only_the_rest(eval_world: Any) -> None:
    kept = runner.Score(
        question="n1",
        model="fake-model",
        language="en",
        status="ok",
        answer="No data.",
        no_data=True,
        no_data_ok=True,
    )
    skipped = runner.not_run(BY_ID["n2"], "fake-model")
    provider = FakeProvider([FakeTurn(text="No data."), FakeTurn(text="No data.")])
    scores = runner.run(
        NO_DATA[:2],
        eval_world,
        provider,
        0,
        lambda s: None,
        lambda m: None,
        done={"n1": kept, "n2": skipped},
    )
    assert scores[0] is kept
    assert scores[1].status == "ok" and scores[1].question == "n2"
    assert len(provider.requests) == 2  # only n2 was asked (answer + reminder)
    assert runner.from_dict(kept.as_dict()) == kept


def test_conversations_of_the_eval_belong_to_its_own_organization(eval_world: Any) -> None:
    provider = FakeProvider([FakeTurn(text="No data."), FakeTurn(text="No data.")])
    runner.run(NO_DATA[:1], eval_world, provider, 0, lambda s: None, lambda m: None)
    conv = Conversation.objects.get(title="[eval] n1")
    assert conv.organization == eval_world.organization
    assert conv.messages.filter(role=MessageRole.ASSISTANT).get().unchecked is True
