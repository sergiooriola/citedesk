from citedesk import Knowledge
from citedesk.instructions import build_instructions


def test_instructions_carry_every_entry_the_office_entries_and_the_rules(
    knowledge: Knowledge,
) -> None:
    text = build_instructions(
        knowledge, office_entry_ids=["OFFICE-01"], rules=["Never state a price."]
    )

    assert '<entry id="DAY-01">\nQuestion: What are the hours?\nAnswer: From 8:45 to 15:30.' in text
    assert '<entry id="OFFICE-01">' in text
    assert "Office entries: OFFICE-01" in text
    assert "- Never state a price." in text


def test_instructions_without_rules_have_no_rules_section(knowledge: Knowledge) -> None:
    text = build_instructions(knowledge, office_entry_ids=["OFFICE-01"])

    assert "Rules of this organisation" not in text


def test_the_same_deployment_always_gets_the_same_text(knowledge: Knowledge) -> None:
    first = build_instructions(knowledge, office_entry_ids=["OFFICE-01"], rules=["A rule."])
    second = build_instructions(knowledge, office_entry_ids=["OFFICE-01"], rules=["A rule."])

    assert first == second


def test_the_language_rule_comes_last_after_the_entries(knowledge: Knowledge) -> None:
    text = build_instructions(knowledge, office_entry_ids=["OFFICE-01"])

    assert text.index("</entry>\n\nWrite your reply in the language") > text.index("Entries:")
    assert text.endswith("leave names as they are.")
