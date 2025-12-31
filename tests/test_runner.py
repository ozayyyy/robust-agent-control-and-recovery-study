"""Runner end-to-end tests: each strategy on each fault class."""

from pathlib import Path

from racrs.agents import CONFIG_BY_NAME
from racrs.runner import run_all, run_scenario
from racrs.scenario import Scenario

ROOT = Path(__file__).resolve().parent.parent
SCENARIOS = {s.id: s for s in Scenario.load_all(ROOT / "scenarios")}


def _run(sid, config, seed=0):
    return run_scenario(SCENARIOS[sid], CONFIG_BY_NAME[config], seed=seed)


def test_benign_completes_for_every_strategy():
    for config in CONFIG_BY_NAME:
        result = _run("benign-01", config)
        assert result.task_completed, config
        assert result.state_matches, config
        assert result.recovery_outcome == "no-fault", config


def test_timeout_baseline_fails_retrying_strategies_recover():
    assert not _run("timeout-01", "baseline").task_completed
    for config in ("retry-only", "state-aware", "policy-constrained"):
        result = _run("timeout-01", config)
        assert result.task_completed and result.recovered, config
        assert result.duplicates == [], config


def test_stale_baseline_duplicates_state_aware_recovers():
    baseline = _run("stale-01", "baseline")
    assert not baseline.task_completed
    assert baseline.duplicates == ["ledger:transfer:acct:ops"]
    assert baseline.final_state["ledger"]["acct:ops"] == 200
    for config in ("state-aware", "policy-constrained"):
        result = _run("stale-01", config)
        assert result.task_completed and result.recovered, config
        assert result.duplicates == [], config
        assert "stale" in result.faults_fired, config


def test_contradictory_baseline_duplicates_state_aware_recovers():
    assert _run("contradictory-01", "baseline").duplicates == \
        ["ledger:transfer:acct:ops"]
    assert _run("contradictory-01", "state-aware").recovered


def test_incomplete_baseline_reorders_state_aware_recovers():
    baseline = _run("incomplete-01", "baseline")
    assert not baseline.task_completed
    assert baseline.duplicates == ["inventory:order:item:widget"]
    assert baseline.final_state["orders"] == 2
    assert _run("incomplete-01", "state-aware").recovered


def test_duplicate_retry_only_is_worse_than_baseline():
    # Baseline does not retry, so it completes once: recovered by luck.
    assert _run("duplicate-01", "baseline").recovered
    retry_only = _run("duplicate-01", "retry-only")
    assert not retry_only.task_completed
    assert retry_only.duplicates == ["ledger:transfer:acct:ops"]
    assert retry_only.final_state["ledger"]["acct:ops"] == 200
    # Verifying strategies do not retry a completed action.
    assert _run("duplicate-01", "state-aware").recovered
    assert _run("duplicate-01", "policy-constrained").recovered


def test_unavailable_fails_everywhere_but_state_aware_aborts_cleanly():
    for config in CONFIG_BY_NAME:
        assert not _run("unavailable-01", config).task_completed
    assert _run("unavailable-01", "baseline").clean_abort is False
    assert _run("unavailable-01", "state-aware").clean_abort is True
    assert _run("unavailable-01", "policy-constrained").clean_abort is True


def test_partial_failure_state_aware_compensates():
    baseline = _run("partial-01", "baseline")
    assert not baseline.task_completed
    assert baseline.final_state["inventory"]["item:widget"] == 8  # held
    assert baseline.final_state["files"]  # receipt written anyway
    assert baseline.clean_abort is False
    aware = _run("partial-01", "state-aware")
    assert not aware.task_completed
    assert aware.compensations == ["inventory:release:item:widget"]
    assert aware.final_state["inventory"]["item:widget"] == 10  # released
    assert aware.final_state["files"] == {"/workspace/notes.txt":
                                          "Task notes. Pay only what the task states."}
    assert aware.clean_abort is True


def test_rollback_refunds_and_releases():
    aware = _run("rollback-01", "state-aware")
    assert not aware.task_completed
    assert aware.compensations == ["ledger:transfer:acct:main",
                                   "inventory:release:item:gadget"]
    assert aware.final_state["ledger"] == {"acct:main": 1000, "acct:ops": 0,
                                           "acct:vendor": 0}
    assert aware.final_state["inventory"]["item:gadget"] == 5
    assert aware.clean_abort is True
    baseline = _run("rollback-01", "baseline")
    assert baseline.final_state["ledger"]["acct:vendor"] == 300
    assert baseline.final_state["inventory"]["item:gadget"] == 2
    assert baseline.clean_abort is False


def test_confirmation_policy_blocks_large_payment_only():
    for config in ("baseline", "retry-only", "state-aware"):
        assert _run("confirmation-01", config).task_completed, config
    policy = _run("confirmation-01", "policy-constrained")
    assert not policy.task_completed
    assert policy.blocked == ["ledger:transfer:acct:vendor"]
    assert policy.approvals_denied == 1
    assert policy.final_state["ledger"]["acct:vendor"] == 0
    assert policy.clean_abort is True  # blocked cleanly, nothing moved
    # Below the threshold the same gate approves.
    assert _run("confirmation-02", "policy-constrained").task_completed


def test_multi_fault_recovery():
    assert not _run("multi-01", "baseline").task_completed
    for config in ("retry-only", "state-aware", "policy-constrained"):
        result = _run("multi-01", config)
        assert result.task_completed and result.recovered, config
        assert set(result.faults_fired) == {"timeout", "malformed"}, config


def test_action_budget_stops_the_run():
    scenario = SCENARIOS["multi-01"]
    config = CONFIG_BY_NAME["policy-constrained"]
    # Force a tiny budget through a scenario copy with action_budget set.
    import copy
    small = copy.copy(scenario)
    small.action_budget = 2
    from racrs.runner import run_scenario as run
    result = run(small, config, seed=0)
    assert result.budget_exceeded is True
    assert result.tool_calls == 2
    assert not result.task_completed


def test_determinism_same_seed_same_result():
    first = _run("stale-01", "state-aware", seed=1)
    second = _run("stale-01", "state-aware", seed=1)
    assert first.to_dict() == second.to_dict()
    third = run_all([SCENARIOS["multi-01"]],
                    [CONFIG_BY_NAME["retry-only"]], seeds=(0, 1, 2))
    assert len(third) == 3
    assert all(r.task_completed for r in third)


def test_trace_is_jsonl_with_7_fields():
    result = _run("stale-01", "state-aware")
    lines = result.trace.to_jsonl().splitlines()
    assert lines[0].startswith('{"trace":')
    import json
    for line in lines[1:]:
        event = json.loads(line)
        assert set(event) == {"seq", "kind", "actor", "summary", "detail"}
        assert event["kind"] in ("decision", "tool_call", "policy",
                                 "approval", "observation", "result")
