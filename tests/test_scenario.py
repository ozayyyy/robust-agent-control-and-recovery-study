"""Scenario schema tests."""

from pathlib import Path

import pytest

from racrs.scenario import Scenario

ROOT = Path(__file__).resolve().parent.parent


def _base(**overrides):
    data = {
        "id": "test-01", "version": "1.0", "category": "benign",
        "title": "Test", "user_task": "Transfer 100.",
        "scope": {},
        "setup": {"ledger": {"acct:main": 1000, "acct:ops": 0}},
        "legitimate_steps": [
            {"tool": "ledger", "op": "transfer", "target": "acct:ops",
             "args": {"from": "acct:main", "amount": 100}}],
        "expected": {"must_complete": ["ledger:transfer:acct:ops"],
                     "must_not_complete": []},
    }
    data.update(overrides)
    return data


def test_all_shipped_scenarios_load():
    scenarios = Scenario.load_all(ROOT / "scenarios")
    assert len(scenarios) == 13
    ids = {s.id for s in scenarios}
    assert ids == {
        "benign-01", "timeout-01", "malformed-01", "unavailable-01",
        "stale-01", "incomplete-01", "contradictory-01", "duplicate-01",
        "partial-01", "rollback-01", "confirmation-01", "confirmation-02",
        "multi-01",
    }


def test_unknown_category_rejected():
    with pytest.raises(ValueError, match="unknown category"):
        Scenario.from_dict(_base(category="no-such-category"))


def test_missing_expected_lists_rejected():
    with pytest.raises(ValueError, match="missing expected"):
        Scenario.from_dict(_base(expected={}))


def test_unknown_fault_rejected():
    with pytest.raises(ValueError, match="unknown fault"):
        Scenario.from_dict(_base(
            fault_schedule={"ledger:transfer:acct:ops":
                            {"fault": "explodes", "fail_times": 1}}))


def test_observation_fault_on_non_read_rejected():
    with pytest.raises(ValueError, match="non-read"):
        Scenario.from_dict(_base(
            fault_schedule={"ledger:transfer:acct:ops":
                            {"fault": "stale", "fail_times": 1}}))


def test_observation_fault_on_read_accepted():
    scenario = Scenario.from_dict(_base(
        fault_schedule={"ledger:balance:acct:ops":
                        {"fault": "stale", "fail_times": 1}}))
    assert scenario.faults["ledger:balance:acct:ops"]["fault"] == "stale"


def test_fault_schedule_wins_over_tool_faults():
    scenario = Scenario.from_dict(_base(
        tool_faults={"ledger:transfer:acct:ops":
                     {"fault": "timeout", "fail_times": 1}},
        fault_schedule={"ledger:transfer:acct:ops":
                        {"fault": "malformed", "fail_times": 2}}))
    assert scenario.faults["ledger:transfer:acct:ops"]["fault"] == "malformed"


def test_tool_faults_used_when_no_fault_schedule():
    scenario = Scenario.from_dict(_base(
        tool_faults={"ledger:transfer:acct:ops":
                     {"fault": "timeout", "fail_times": 1}}))
    assert scenario.faults["ledger:transfer:acct:ops"]["fault"] == "timeout"


def test_plan_steps_and_compensation_parse():
    scenario = Scenario.from_dict(_base(
        plan_steps=[{
            "action": {"tool": "ledger", "op": "transfer", "target": "acct:ops",
                       "args": {"from": "acct:main", "amount": 100}},
            "postcondition": {"tool": "ledger", "op": "balance",
                              "target": "acct:ops",
                              "expected_contains": "BALANCE: acct:ops=100"},
            "compensate": [{"tool": "ledger", "op": "transfer",
                            "target": "acct:main",
                            "args": {"from": "acct:ops", "amount": 100}}]}]))
    step = scenario.plan_step_for(scenario.legitimate_steps[0])
    assert step is not None
    assert step.postcondition["expected_contains"] == "BALANCE: acct:ops=100"
    assert step.compensate[0].key() == "ledger:transfer:acct:main"


def test_racrs_extension_defaults_on_7_format():
    scenario = Scenario.from_dict(_base())
    assert scenario.fault_schedule == {}
    assert scenario.plan_steps == []
    assert scenario.expected_final_state == {}
    assert scenario.observation_followups == []
    assert scenario.confirmation_threshold == 0
    assert scenario.action_budget == 0


def test_duplicate_ids_rejected(tmp_path):
    first = tmp_path / "a.json"
    second = tmp_path / "b.json"
    import json
    for path in (first, second):
        path.write_text(json.dumps(_base()), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate scenario ids"):
        Scenario.load_all(tmp_path)


def test_round_trip_through_dict():
    scenario = Scenario.load(ROOT / "scenarios" / "rollback-01.json")
    restored = Scenario.from_dict(scenario.to_dict())
    assert restored.id == scenario.id
    assert restored.faults == scenario.faults
    assert len(restored.plan_steps) == len(scenario.plan_steps)
    assert restored.expected_final_state == scenario.expected_final_state
