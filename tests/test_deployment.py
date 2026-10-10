import asyncio
import json
from pathlib import Path

import pytest

from citedesk import Generation, KnowledgeError, Turn, Usage
from citedesk.deployment import Deployment, DeploymentError, Limits, Prices

from .conftest import ScriptedModel

ENTRIES = (
    '{"id": "DAY-01", "question": "What are the hours?", "answer": "From 8:45 to 15:30."}\n'
    '{"id": "OFFICE-01", "question": "How do I reach the office?", "answer": "Call 555 0100."}\n'
)


def write(folder: Path, **changes: object) -> Path:
    (folder / "entries.jsonl").write_text(ENTRIES, encoding="utf-8")
    content = {
        "knowledge": "entries.jsonl",
        "office_entry_ids": ["OFFICE-01"],
        "fallback": "Call 555 0100.",
        "rules": ["Never state a fee."],
    } | changes
    path = folder / "deployment.json"
    path.write_text(json.dumps(content), encoding="utf-8")
    return path


def test_a_file_becomes_a_deployment_with_its_entries(tmp_path: Path) -> None:
    deployment = Deployment.from_file(write(tmp_path))

    assert [entry.id for entry in deployment.knowledge] == ["DAY-01", "OFFICE-01"]
    assert deployment.office_entry_ids == ("OFFICE-01",)
    assert deployment.fallback == "Call 555 0100."
    assert deployment.rules == ("Never state a fee.",)
    assert (deployment.model, deployment.effort) == ("claude-haiku-5-5", "low")


def test_a_deployment_has_limits_by_default_and_no_prices(tmp_path: Path) -> None:
    deployment = Deployment.from_file(write(tmp_path))

    assert deployment.limits == Limits(
        message_chars=600,
        turns=20,
        client_requests_per_minute=6,
        requests_per_minute=60,
        daily_budget_usd=1.0,
    )
    assert deployment.prices is None


def test_a_deployment_can_set_its_limits_and_prices(tmp_path: Path) -> None:
    prices = {"input": 0.1, "output": 0.5, "cache_read": 0.01, "cache_write": 0.125}
    path = write(tmp_path, limits={"daily_budget_usd": 0.5, "turns": 8}, prices=prices)

    deployment = Deployment.from_file(path)

    assert (deployment.limits.daily_budget_usd, deployment.limits.turns) == (0.5, 8)
    assert deployment.limits.message_chars == 600
    assert deployment.prices == Prices(**prices)


def test_prices_turn_usage_into_dollars() -> None:
    prices = Prices(input=0.1, output=0.5, cache_read=0.01, cache_write=0.125)
    usage = Usage(
        input_tokens=1_000_000,
        output_tokens=2_000_000,
        cache_read_tokens=10_000_000,
        cache_write_tokens=4_000_000,
    )

    assert prices.cost(usage) == pytest.approx(0.1 + 1.0 + 0.1 + 0.5)


def test_a_deployment_can_set_its_model_and_effort(tmp_path: Path) -> None:
    deployment = Deployment.from_file(write(tmp_path, model="a-model", effort="medium"))

    assert (deployment.model, deployment.effort) == ("a-model", "medium")


def test_the_entries_file_is_found_next_to_the_deployment_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write(tmp_path)
    monkeypatch.chdir(tmp_path.parent)

    assert len(Deployment.from_file(path).knowledge) == 2


@pytest.mark.parametrize(
    "changes",
    [
        {"office_entry_ids": []},
        {"fallback": " "},
        {"knowledge": ""},
        {"effort": "extreme"},
        {"limits": {"turns": 0}},
        {"limits": {"daily_budget_usd": -1}},
        {"prices": {"input": 0.1}},
        {"unexpected": True},
    ],
)
def test_a_file_that_is_not_a_deployment_is_refused(
    tmp_path: Path, changes: dict[str, object]
) -> None:
    with pytest.raises(DeploymentError, match=r"deployment\.json: not a valid deployment"):
        Deployment.from_file(write(tmp_path, **changes))


def test_its_assistant_carries_the_rules_the_office_entries_and_the_fallback(
    deployment: Deployment,
) -> None:
    model = ScriptedModel(Generation("failed"))

    reply = asyncio.run(deployment.assistant(model).reply([Turn("user", "Hours?")]))

    assert "- Fees are reserved for the office." in model.instructions
    assert "Office entries: OFFICE-01" in model.instructions
    assert reply.text == "The office can help: call 555 0100."


def test_an_office_entry_missing_from_the_entries_is_refused(tmp_path: Path) -> None:
    deployment = Deployment.from_file(write(tmp_path, office_entry_ids=["OFFICE-09"]))

    with pytest.raises(KnowledgeError, match="OFFICE-09"):
        deployment.assistant(ScriptedModel(Generation("failed")))
