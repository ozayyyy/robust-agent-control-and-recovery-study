"""Agent strategy tests: retry, verification, idempotency, compensation."""

from pathlib import Path

from racrs.agents import (BASELINE, CONFIG_BY_NAME, POLICY_CONSTRAINED,
                         RETRY_ONLY, STATE_AWARE, SimulatedAgent)
from racrs.permissions import Action
from racrs.scenario import Scenario

ROOT = Path(__file__).resolve().parent.parent


def _scenario(sid="timeout-01"):
    return Scenario.load(ROOT / "scenarios" / f"{sid}.json")


def _action():
    return Action("ledger", "transfer", "acct:ops",
                  {"from": "acct:main", "amount": 100})


def test_four_configs_exist_with_distinct_policies():
    assert list(CONFIG_BY_NAME) == [
        "baseline", "retry-only", "state-aware", "policy-constrained"]
    assert BASELINE.max_retries == 0
    assert RETRY_ONLY.max_retries == 2
    assert STATE_AWARE.verify_postconditions
    assert STATE_AWARE.use_idempotency
    assert POLICY_CONSTRAINED.tool_enforcement
    assert POLICY_CONSTRAINED.approval_mode == "gate"
    assert POLICY_CONSTRAINED.action_budget == 12


def test_should_retry_matrix():
    action = _action()
    cases = [
        # (config, fault, already_completed, expected)
        ("baseline", "timeout", False, False),
        ("baseline", "duplicate", True, False),
        ("retry-only", "timeout", False, True),
        ("retry-only", "malformed", False, True),
        ("retry-only", "duplicate", True, True),  # the duplicate flaw
        ("retry-only", "unavailable", False, False),
        ("retry-only", "postcondition-failed", False, False),
        ("state-aware", "timeout", False, True),
        ("state-aware", "duplicate", True, False),  # verifies first
        ("state-aware", "postcondition-failed", False, True),
        ("state-aware", "unavailable", False, False),
        ("policy-constrained", "timeout", False, True),
        ("policy-constrained", "duplicate", True, False),
    ]
    for name, fault, done, expected in cases:
        agent = SimulatedAgent(CONFIG_BY_NAME[name])
        assert agent.should_retry(action, fault, done, 0) is expected, \
            (name, fault, done)
    # Retries are bounded by max_retries.
    agent = SimulatedAgent(CONFIG_BY_NAME["retry-only"])
    assert agent.should_retry(action, "timeout", False, 2) is False


def test_idempotency_keys_only_for_verifying_configs():
    scenario = _scenario("benign-01")
    action = _action()
    for name in ("baseline", "retry-only"):
        agent = SimulatedAgent(CONFIG_BY_NAME[name])
        assert agent.idempotency_key(action, scenario) is None
    for name in ("state-aware", "policy-constrained"):
        agent = SimulatedAgent(CONFIG_BY_NAME[name])
        assert agent.idempotency_key(action, scenario) == \
            "benign-01:ledger:transfer:acct:ops"
    # Reads never get a key.
    agent = SimulatedAgent(CONFIG_BY_NAME["state-aware"])
    assert agent.idempotency_key(
        Action("ledger", "balance", "acct:ops"), scenario) is None


def test_plan_legitimate_attaches_idempotency_keys():
    scenario = _scenario("benign-01")
    agent = SimulatedAgent(CONFIG_BY_NAME["state-aware"])
    plan = agent.plan_legitimate(scenario)
    transfer = plan[0]
    assert transfer.args["idempotency_key"] == \
        "benign-01:ledger:transfer:acct:ops"
    # The scenario's own steps are not mutated.
    assert "idempotency_key" not in scenario.legitimate_steps[0].args


def test_compensation_for_returns_plan_compensations():
    scenario = _scenario("rollback-01")
    agent = SimulatedAgent(CONFIG_BY_NAME["state-aware"])
    reserve = Action("inventory", "reserve", "item:gadget", {"qty": 3})
    compensations = agent.compensation_for(reserve, scenario)
    assert [a.key() for a in compensations] == ["inventory:release:item:gadget"]
    transfer = Action("ledger", "transfer", "acct:vendor",
                      {"from": "acct:main", "amount": 300})
    compensations = agent.compensation_for(transfer, scenario)
    assert [a.key() for a in compensations] == ["ledger:transfer:acct:main"]


def test_observation_followups_followed_from_raw_observation():
    scenario = _scenario("stale-01")
    agent = SimulatedAgent(CONFIG_BY_NAME["baseline"])
    follow_ups = agent.plan_after_observation(
        scenario, ["BALANCE: acct:ops=0"])
    assert [a.key() for a in follow_ups] == ["ledger:transfer:acct:ops"]
    # The verified observation does not trigger the follow-up.
    follow_ups = agent.plan_after_observation(
        scenario, ["BALANCE: acct:ops=100"])
    assert follow_ups == []


def test_should_refuse_defaults_to_false():
    scenario = _scenario("benign-01")
    for name in CONFIG_BY_NAME:
        agent = SimulatedAgent(CONFIG_BY_NAME[name])
        assert agent.should_refuse(scenario) is False
