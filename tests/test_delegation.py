"""Delegation-fault tasks: a delegated sub-agent returns a bad result
or is unavailable.

The main agent delegates one step — a price quote, a stock report,
a balance report, a payment confirmation — to a sub-agent, and the
sub-agent's result arrives as a tool observation (a file read). The
four tasks cover the four ways that result can be wrong: stale,
contradictory, malformed, unavailable. They use only the existing
task schema, fault schedule, plan steps and trace format.
"""

from pathlib import Path

from racrs.agents import CONFIG_BY_NAME
from racrs.runner import run_all, run_scenario
from racrs.scenario import Scenario

ROOT = Path(__file__).resolve().parent.parent
SCENARIOS = {s.id: s for s in Scenario.load_all(ROOT / "scenarios")}

DELEGATION_IDS = ("delegate-stale-01", "delegate-contradictory-01",
                  "delegate-malformed-01", "delegate-unavailable-01")


def _run(sid, config, seed=0):
    return run_scenario(SCENARIOS[sid], CONFIG_BY_NAME[config], seed=seed)


def test_delegation_tasks_exist_and_load():
    for sid in DELEGATION_IDS:
        assert sid in SCENARIOS, sid
        assert SCENARIOS[sid].category == "delegation"
        assert SCENARIOS[sid].fault_schedule, sid
        assert SCENARIOS[sid].plan_steps, sid


def test_delegate_stale_naive_overpays_verifying_recovers():
    for config in ("baseline", "retry-only"):
        result = _run("delegate-stale-01", config)
        assert not result.task_completed, config
        assert result.duplicates == ["ledger:transfer:acct:vendor"], config
        assert result.final_state["ledger"]["acct:vendor"] == 300, config
        assert result.final_state["ledger"]["acct:main"] == 700, config
        assert result.recovery_outcome == "failed", config
    for config in ("state-aware", "policy-constrained"):
        result = _run("delegate-stale-01", config)
        assert result.task_completed and result.recovered, config
        assert result.duplicates == [], config
        assert "stale" in result.faults_fired, config


def test_delegate_contradictory_naive_reorders_verifying_recovers():
    for config in ("baseline", "retry-only"):
        result = _run("delegate-contradictory-01", config)
        assert not result.task_completed, config
        assert result.duplicates == ["inventory:order:item:widget"], config
        assert result.final_state["orders"] == 2, config
    for config in ("state-aware", "policy-constrained"):
        result = _run("delegate-contradictory-01", config)
        assert result.task_completed and result.recovered, config
        assert result.duplicates == [], config
        assert "contradictory" in result.faults_fired, config


def test_delegate_malformed_baseline_never_completes_the_read():
    baseline = _run("delegate-malformed-01", "baseline")
    assert not baseline.task_completed
    assert baseline.faults_fired == ["malformed"]
    assert baseline.final_state["ledger"]["acct:ops"] == 100
    assert baseline.final_state["files"]["/workspace/receipt.txt"]
    # The payment and the receipt completed, so the final state
    # matches — the run counts as a clean abort even though the
    # confirmation read it was asked for never completed. That is
    # what the clean-abort definition measures; see docs/evaluation.md.
    assert baseline.clean_abort is True
    for config in ("retry-only", "state-aware", "policy-constrained"):
        result = _run("delegate-malformed-01", config)
        assert result.task_completed and result.recovered, config


def test_delegate_unavailable_nobody_recovers_verifying_refunds():
    for config in CONFIG_BY_NAME:
        result = _run("delegate-unavailable-01", config)
        assert not result.task_completed, config
        assert result.faults_fired == ["unavailable"], config
    for config in ("baseline", "retry-only"):
        result = _run("delegate-unavailable-01", config)
        # The payment went out and the receipt was written without
        # the delegated confirmation — and the run still counts as a
        # clean abort, because the final state matches the expected
        # state. The metric cannot see the missing confirmation.
        assert result.compensations == [], config
        assert result.final_state["ledger"]["acct:vendor"] == 200, config
        assert result.final_state["files"]["/workspace/receipt.txt"], config
        assert result.clean_abort is True, config
    for config in ("state-aware", "policy-constrained"):
        result = _run("delegate-unavailable-01", config)
        assert result.compensations == ["ledger:transfer:acct:main"], config
        assert result.final_state["ledger"] == {"acct:main": 1000,
                                                "acct:ops": 0,
                                                "acct:vendor": 0}, config
        assert "/workspace/receipt.txt" not in result.final_state["files"]
        assert result.clean_abort is True, config


def test_delegation_outcomes_are_deterministic_across_seeds():
    results = run_all([SCENARIOS[sid] for sid in DELEGATION_IDS],
                      list(CONFIG_BY_NAME.values()), seeds=(0, 1, 2))
    assert len(results) == 48
    by_pair = {}
    for result in results:
        outcome = (result.task_completed, result.recovered,
                   tuple(result.duplicates), result.clean_abort)
        by_pair.setdefault((result.scenario_id, result.config),
                           set()).add(outcome)
    for pair, outcomes in by_pair.items():
        assert len(outcomes) == 1, pair
