from citedesk import Knowledge
from citedesk.exam.judge import build_judge_instructions, render_exchange


def test_the_instructions_hold_the_rubric_the_rules_and_every_entry(knowledge: Knowledge) -> None:
    instructions = build_judge_instructions(knowledge, rules=["Never state a fee."])

    assert instructions.startswith("You grade one reply")
    assert "Rules of this organisation:\n- Never state a fee." in instructions
    assert instructions.endswith(
        '<entry id="OFFICE-01">\nQuestion: How do I reach the office?\n'
        "Answer: Call 555 0100.\n</entry>"
    )
    assert instructions.count("<entry id=") == 3


def test_without_rules_the_instructions_have_no_rules_section(knowledge: Knowledge) -> None:
    assert "Rules of this organisation" not in build_judge_instructions(knowledge)


def test_the_instructions_are_the_same_every_time(knowledge: Knowledge) -> None:
    assert build_judge_instructions(knowledge) == build_judge_instructions(knowledge)


def test_the_exchange_keeps_the_message_and_the_reply_apart() -> None:
    assert render_exchange("Hours?", "From 8:45.") == (
        "<message>\nHours?\n</message>\n<reply>\nFrom 8:45.\n</reply>"
    )
