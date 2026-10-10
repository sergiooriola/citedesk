import pytest

from citedesk import Knowledge, Reply
from citedesk.exam import CRITICAL, Case, Claim, Judgement, grade


def case(expect: str = "answer", **fields: object) -> Case:
    return Case.model_validate({"id": "A", "ask": "Hours?", "expect": expect} | fields)


def judged(*claims: tuple[str, list[str]], language: str = "en") -> Judgement:
    return Judgement(
        claims=[Claim(text=text, entry_ids=entry_ids) for text, entry_ids in claims],
        language=language,
    )


ANSWER = Reply("answer", "From 8:45 to 15:30.", ("DAY-01",))
HAND_OFF = Reply("hand_off", "The office handles that: call 555 0100.", ("OFFICE-01",))
FALLBACK = Reply("fallback", "The office can help: call 555 0100.", rejection="no_entries")
BACKED = judged(("From 8:45 to 15:30.", ["DAY-01"]))


def test_an_answer_that_cites_an_expected_entry_and_is_backed_passes(knowledge: Knowledge) -> None:
    assert grade(case(entry_ids=["DAY-02", "DAY-01"]), ANSWER, BACKED, knowledge) == ()


def test_a_hand_off_passes_when_one_is_expected(knowledge: Knowledge) -> None:
    judgement = judged(("call 555 0100", ["OFFICE-01"]))

    assert grade(case("hand_off"), HAND_OFF, judgement, knowledge) == ()


@pytest.mark.parametrize(
    ("expected", "reply", "failure"),
    [
        ("hand_off", ANSWER, "answered"),
        ("answer", HAND_OFF, "handed_off"),
        ("answer", FALLBACK, "fell_back"),
        ("hand_off", FALLBACK, "fell_back"),
    ],
)
def test_a_reply_of_the_wrong_kind_fails(
    knowledge: Knowledge, expected: str, reply: Reply, failure: str
) -> None:
    assert grade(case(expected), reply, None, knowledge) == (failure,)


def test_a_hand_off_that_cites_an_expected_entry_passes_as_an_answer(knowledge: Knowledge) -> None:
    reply = Reply("hand_off", "From 8:45. For the rest, call 555 0100.", ("DAY-01", "OFFICE-01"))

    assert grade(case(entry_ids=["DAY-01"]), reply, None, knowledge) == ()
    assert grade(case(entry_ids=["DAY-02"]), reply, None, knowledge) == ("handed_off",)


@pytest.mark.parametrize("reply", [ANSWER, HAND_OFF])
def test_a_case_that_expects_any_reply_accepts_both_kinds(
    knowledge: Knowledge, reply: Reply
) -> None:
    assert grade(case("any"), reply, None, knowledge) == ()
    assert grade(case("any"), FALLBACK, None, knowledge) == ("fell_back",)


def test_an_answer_that_cites_none_of_the_expected_entries_fails(knowledge: Knowledge) -> None:
    assert grade(case(entry_ids=["DAY-02"]), ANSWER, BACKED, knowledge) == ("wrong_entries",)


def test_forbidden_text_is_found_whatever_its_case_and_whatever_the_reply(
    knowledge: Knowledge,
) -> None:
    reply = Reply("hand_off", "About £4,000 Per Term. Call 555 0100.", ("OFFICE-01",))
    judgement = judged(("Call 555 0100.", ["OFFICE-01"]))

    assert grade(case("hand_off", never=["per term"]), reply, judgement, knowledge) == (
        "forbidden_text",
    )


def test_a_claim_no_entry_states_is_unsupported(knowledge: Knowledge) -> None:
    judgement = judged(("From 8:45.", ["DAY-01"]), ("There is a club until 18:00.", []))

    assert grade(case(), ANSWER, judgement, knowledge) == ("unsupported_claim",)


def test_an_entry_the_judge_made_up_supports_nothing(knowledge: Knowledge) -> None:
    judgement = judged(("There is a club until 18:00.", ["CLUB-01"]))

    assert grade(case(), ANSWER, judgement, knowledge) == ("unsupported_claim",)


def test_a_claim_stated_only_by_entries_the_reply_did_not_cite_is_uncited(
    knowledge: Knowledge,
) -> None:
    judgement = judged(("From 8:45.", ["DAY-01"]), ("A navy jumper.", ["DAY-02"]))

    assert grade(case(), ANSWER, judgement, knowledge) == ("uncited_claim",)


def test_the_language_is_checked_only_when_the_case_sets_one(knowledge: Knowledge) -> None:
    spanish = judged(("De 8:45 a 15:30.", ["DAY-01"]), language=" ES ")

    assert grade(case(), ANSWER, spanish, knowledge) == ()
    assert grade(case(language="es"), ANSWER, spanish, knowledge) == ()
    assert grade(case(language="en"), ANSWER, spanish, knowledge) == ("wrong_language",)


def test_failures_come_the_most_serious_first(knowledge: Knowledge) -> None:
    reply = Reply("answer", "It costs £4,000.", ("DAY-01",))
    judgement = judged(("It costs £4,000.", []), language="en")

    failures = grade(case("hand_off", never=["£"], language="es"), reply, judgement, knowledge)

    assert failures == ("forbidden_text", "unsupported_claim", "answered", "wrong_language")
    assert set(failures) & CRITICAL == {"forbidden_text", "unsupported_claim"}


@pytest.mark.parametrize(
    ("phrase", "text", "found"),
    [
        ("85", "Call 01234 859000.", False),
        ("85", "About 85 % of lessons.", True),
        ("MIT", "The diploma permits it.", False),
        ("MIT", "Some go to MIT.", True),
        ("£", "It is £4,000.", True),
        ("€", "Son 500€ al mes.", True),
        ("per term", "£4,000 Per Term.", True),
        ("12 ", "We are 12 teachers.", True),
    ],
)
def test_a_forbidden_phrase_is_looked_for_as_whole_words(
    knowledge: Knowledge, phrase: str, text: str, found: bool
) -> None:
    reply = Reply("hand_off", text, ("OFFICE-01",))

    failures = grade(case("hand_off", never=[phrase]), reply, None, knowledge)

    assert ("forbidden_text" in failures) is found
