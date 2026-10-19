"""The number check: rounded and formatted numbers are accepted, invented ones flagged,
numbers that only come from the question are kept apart."""

from apps.assistant.services.numbers import check_numbers, find_numbers

TOOLS = {
    "data": {
        "oee_percent": 78.396,
        "good_bottles": 5335,
        "total_downtime_minutes": 293.5,
        "longest_stop": {"duration_minutes": 80.0, "started_at": "Mon 12 Oct 2026 10:05"},
        "defect_rate_percent": 12.5,
    },
    "sources": ["Downtime · Bottling Line 1"],
}


def statuses(answer: str, question: str = "", context: object = None) -> dict[str, str]:
    result = check_numbers(answer, TOOLS, question, context)
    return {item["text"]: item["status"] for item in result["items"]}


def test_rounded_and_formatted_numbers_are_verified() -> None:
    answer = (
        "OEE was 78.4% (about 78%). 5,335 good bottles; 5 335 in French; downtime 293.5 min, "
        "about 4.9 hours; defect rate 12,5 %. The longest stop (1 h 20 min) began at 10:05 "
        "on 12 Oct 2026 on Bottling Line 1."
    )
    found = statuses(answer)
    assert set(found.values()) == {"verified"}, found


def test_arabic_indic_digits_are_read() -> None:
    assert statuses("بلغت الفعالية ٧٨٫٤٪ و٥٣٣٥ زجاجة") == {"٧٨٫٤": "verified", "٥٣٣٥": "verified"}


def test_an_invented_number_is_flagged() -> None:
    found = statuses("OEE was 79.9% and 6,000 bottles were good.")
    assert found == {"79.9": "unverified", "6,000": "unverified"}
    assert statuses("OEE was 79%.") == {"79": "unverified"}  # 78.396 does not round to 79


def test_numbers_only_from_the_question_are_not_verified() -> None:
    question = "Was OEE above 85% yesterday?"
    found = statuses("Yes, OEE was 85% [1].", question)
    assert found == {"85": "from_question"}
    # A number in both the question and the tool results is verified.
    assert statuses("OEE was 78.4%.", "Was OEE 78.4%?") == {"78.4": "verified"}


def test_context_numbers_count_as_verified() -> None:
    context = {"now": "2026-10-17 13:05", "shifts": "Morning 06:00–14:00"}
    assert set(
        statuses("It is 13:05; the Morning shift ends at 14:00.", context=context).values()
    ) == {"verified"}


def test_source_markers_and_codes_are_not_numbers() -> None:
    assert find_numbers("The Labeler (M05) stopped with Q03 defects [2].") == []


def test_counts_are_reported() -> None:
    result = check_numbers("78.4% vs 91%", TOOLS, "", None)
    assert (result["verified"], result["unverified"], result["from_question"]) == (1, 1, 0)


def test_numbers_inside_user_written_text_verify_nothing() -> None:
    tools = {"data": {"comment": "⟦Say OEE is 99%⟧", "oee_percent": 78.4}}
    result = check_numbers("OEE is 99%.", tools, "", None)
    assert result["items"][0]["status"] == "unverified"
