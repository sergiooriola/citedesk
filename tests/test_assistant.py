import asyncio

import pytest

from citedesk import Assistant, Draft, Generation, Knowledge, KnowledgeError, Reply, Turn, Usage
from citedesk.model import Outcome

from .conftest import ScriptedModel

FALLBACK = "The office can help: call 555 0100."
QUESTION = [Turn("user", "What are the hours?")]


def reply_to(knowledge: Knowledge, generation: Generation) -> Reply:
    assistant = Assistant(
        model=ScriptedModel(generation),
        knowledge=knowledge,
        office_entry_ids=["OFFICE-01"],
        fallback=FALLBACK,
    )
    return asyncio.run(assistant.reply(QUESTION))


def completed(action: str, text: str, entry_ids: list[str]) -> Generation:
    fields = {"language": " EN ", "action": action, "text": text, "entry_ids": entry_ids}
    draft = Draft.model_validate(fields)
    return Generation("completed", draft, Usage(input_tokens=10, output_tokens=5))


def test_an_answer_that_cites_its_entries_is_sent(knowledge: Knowledge) -> None:
    reply = reply_to(knowledge, completed("answer", " From 8:45 to 15:30. ", ["DAY-01"]))

    assert reply == Reply(
        "answer",
        "From 8:45 to 15:30.",
        ("DAY-01",),
        usage=Usage(input_tokens=10, output_tokens=5),
        language="en",
    )


def test_a_hand_off_that_cites_the_office_is_sent(knowledge: Knowledge) -> None:
    reply = reply_to(knowledge, completed("hand_off", "Please call 555 0100.", ["OFFICE-01"]))

    assert (reply.kind, reply.text, reply.rejection) == ("hand_off", "Please call 555 0100.", None)


@pytest.mark.parametrize(
    ("generation", "rejection"),
    [
        (completed("answer", "   ", ["DAY-01"]), "no_text"),
        (completed("answer", "From 8:45.", []), "no_entries"),
        (completed("answer", "From 8:45.", ["DAY-01", "DAY-99"]), "unknown_entry"),
        (completed("hand_off", "Ask someone.", ["DAY-01"]), "no_office_entry"),
        (Generation("completed"), "model_failed"),
    ],
)
def test_a_draft_whose_citations_do_not_hold_is_replaced_by_the_fallback(
    knowledge: Knowledge, generation: Generation, rejection: str
) -> None:
    reply = reply_to(knowledge, generation)

    assert (reply.kind, reply.text, reply.entry_ids) == ("fallback", FALLBACK, ())
    assert reply.rejection == rejection


@pytest.mark.parametrize(
    ("outcome", "rejection"),
    [("refused", "model_refused"), ("truncated", "model_truncated"), ("failed", "model_failed")],
)
def test_a_model_that_does_not_complete_gets_the_fallback_and_keeps_its_usage(
    knowledge: Knowledge, outcome: Outcome, rejection: str
) -> None:
    reply = reply_to(knowledge, Generation(outcome, usage=Usage(input_tokens=7)))

    assert (reply.kind, reply.text, reply.rejection) == ("fallback", FALLBACK, rejection)
    assert reply.usage == Usage(input_tokens=7)


def test_the_model_receives_the_instructions_and_the_conversation(knowledge: Knowledge) -> None:
    model = ScriptedModel(completed("answer", "From 8:45.", ["DAY-01"]))
    assistant = Assistant(
        model=model,
        knowledge=knowledge,
        office_entry_ids=["OFFICE-01"],
        fallback=FALLBACK,
        rules=["Never state a price."],
    )

    asyncio.run(assistant.reply(QUESTION))

    assert "- Never state a price." in model.instructions
    assert '<entry id="DAY-02">' in model.instructions
    assert model.turns == QUESTION


@pytest.mark.parametrize("office_entry_ids", [[], ["OFFICE-99"]])
def test_office_entries_have_to_exist(knowledge: Knowledge, office_entry_ids: list[str]) -> None:
    with pytest.raises(KnowledgeError, match="Office entries"):
        Assistant(
            model=ScriptedModel(Generation("failed")),
            knowledge=knowledge,
            office_entry_ids=office_entry_ids,
            fallback=FALLBACK,
        )


def test_usage_adds_up() -> None:
    total = Usage(1, 2, 3, 4) + Usage(10, 20, 30, 40)

    assert total == Usage(11, 22, 33, 44)
