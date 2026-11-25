"""Counterfactual recovery tests: paired re-runs, fault modes,
helps-vs-hurts, hindsight replanning and the gain fault class."""

import json
from pathlib import Path

import pytest

from racrs.agents import CONFIG_BY_NAME, CONFIGS
from racrs.counterfactual import (
    counterfactual_recovery,
    fresh_schedule,
    hindsight_replan,
    run_counterfactual_study,
)
from racrs.permissions import Action, Scope
from racrs.runner import run_scenario
from racrs.scenario import FAULTS, Scenario
from racrs.tools import Sandbox, ToolSet

ROOT = Path(__file__).resolve().parent.parent
SCENARIOS = {s.id: s for s in Scenario.load_all(ROOT / "scenarios")}

# The fault vocabulary before this module: no shipped task uses
# "gain" — the new class exists in the code and the tests only.
OLD_FAULTS = ("timeout", "malformed", "unavailable", "duplicate",
              "stale", "incomplete", "contradictory")


def _gain_scenario(factor=2, fail_times=1):
    """A transfer task with a gain fault, built in memory from
    benign-01. No shipped task file is touched."""
    data = json.loads((ROOT / "scenarios" / "benign-01.json").read_text())
    data["id"] = "gain-test-01"
    data["fault_schedule"] = {"ledger:transfer:acct:ops":
                              {"fault": "gain", "factor": factor,
                               "fail_times": fail_times}}
    return Scenario.from_dict(data)


def _tools(faults=None, **setup):
    sandbox = Sandbox.from_setup(setup)
    return ToolSet(sandbox, Scope(), faults=faults), sandbox


# -- the gain fault class -------------------------------------------

def test_gain_is_a_recognised_fault_value():
    assert "gain" in FAULTS
    # A scenario may carry a gain fault in its schedule.
    assert _gain_scenario().faults == {
        "ledger:transfer:acct:ops": {"fault": "gain", "factor": 2,
                                     "fail_times": 1}}


def test_gain_scales_a_ledger_transfer():
    tools, sandbox = _tools(
        {"ledger:transfer:acct:ops": {"fault": "gain", "factor": 2}},
        ledger={"acct:main": 1000, "acct:ops": 0})
    result, _ = tools.call(Action("ledger", "transfer", "acct:ops",
                                  {"from": "acct:main", "amount": 100}))
    assert result.ok and result.fault == "gain"
    assert sandbox.ledger == {"acct:main": 800, "acct:ops": 200}


def test_gain_factor_three_scales_an_inventory_order():
    tools, sandbox = _tools(
        {"inventory:order:item:widget": {"fault": "gain", "factor": 3}},
        inventory={"item:widget": 10})
    result, _ = tools.call(Action("inventory", "order", "item:widget",
                                  {"qty": 2}))
    assert result.ok and result.fault == "gain"
    assert sandbox.inventory["item:widget"] == 4  # 10 - 2*3
    assert sandbox.orders[0]["qty"] == 6


def test_gain_scales_a_balance_read():
    tools, _ = _tools(
        {"ledger:balance:acct:ops": {"fault": "gain", "factor": 2}},
        ledger={"acct:main": 900, "acct:ops": 100})
    result, _ = tools.call(Action("ledger", "balance", "acct:ops"))
    assert result.ok and result.fault == "gain"
    assert result.output == "BALANCE: acct:ops=200"


def test_gain_applies_for_fail_times_then_stops():
    tools, sandbox = _tools(
        {"ledger:transfer:acct:ops": {"fault": "gain", "factor": 2,
                                      "fail_times": 2}},
        ledger={"acct:main": 1000, "acct:ops": 0})
    action = Action("ledger", "transfer", "acct:ops",
                    {"from": "acct:main", "amount": 100})
    tools.call(action)  # scaled: 200
    tools.call(action)  # scaled: 200
    result, _ = tools.call(action)  # third attempt: normal 100
    assert result.ok and result.fault == ""
    assert sandbox.ledger == {"acct:main": 500, "acct:ops": 500}


def test_gain_does_not_fire_on_an_unscalable_action():
    tools, sandbox = _tools(
        {"file:write:/workspace/note.txt": {"fault": "gain", "factor": 2}})
    result, _ = tools.call(Action("file", "write", "/workspace/note.txt",
                                  {"content": "hello"}))
    assert result.ok and result.fault == ""
    assert sandbox.files["/workspace/note.txt"].content == "hello"


def test_gain_factor_one_does_not_fire():
    tools, sandbox = _tools(
        {"ledger:transfer:acct:ops": {"fault": "gain", "factor": 1}},
        ledger={"acct:main": 1000, "acct:ops": 0})
    result, _ = tools.call(Action("ledger", "transfer", "acct:ops",
                                  {"from": "acct:main", "amount": 100}))
    assert result.ok and result.fault == ""
    assert sandbox.ledger == {"acct:main": 900, "acct:ops": 100}


def test_gain_is_unrecoverable_by_retry():
    # The wrong amount is already moved; retrying cannot un-move
    # it. Every strategy fails the gain task, in both modes.
    task = _gain_scenario()
    for mode in ("persistent", "fresh"):
        result = counterfactual_recovery(task, list(CONFIGS),
                                         fault_mode=mode, seeds=(0, 1, 2))
        for name, entry in result.strategies.items():
            assert entry.recovered == 0, (mode, name)
            assert entry.task_completed == 0, (mode, name)


# -- paired re-runs: determinism -------------------------------------

def test_counterfactual_run_is_deterministic():
    first = counterfactual_recovery(SCENARIOS["timeout-01"], list(CONFIGS),
                                    fault_mode="persistent", seeds=(0, 1, 2))
    second = counterfactual_recovery(SCENARIOS["timeout-01"], list(CONFIGS),
                                     fault_mode="persistent", seeds=(0, 1, 2))
    assert first.to_dict() == second.to_dict()


def test_same_fault_fires_for_every_strategy_on_the_same_seed():
    # The event is held fixed: every strategy sees the same fault.
    result = counterfactual_recovery(SCENARIOS["stale-01"], list(CONFIGS),
                                     fault_mode="persistent", seeds=(0,))
    fired = {tuple(entry.runs[0].faults_fired)
             for entry in result.strategies.values()}
    assert fired == {("stale",)}


def test_fresh_mode_does_not_mutate_the_task():
    task = SCENARIOS["timeout-01"]
    before = dict(task.fault_schedule)
    counterfactual_recovery(task, list(CONFIGS), fault_mode="fresh",
                            seeds=(0, 1, 2))
    assert task.fault_schedule == before
    assert task.faults == before


def test_fresh_schedule_is_deterministic_and_varies():
    task = _gain_scenario()
    draws = [fresh_schedule(task, seed)["ledger:transfer:acct:ops"]["factor"]
             for seed in range(6)]
    assert draws == [fresh_schedule(task, seed)
                     ["ledger:transfer:acct:ops"]["factor"]
                     for seed in range(6)]  # same inputs, same draw
    assert len(set(draws)) > 1  # fresh severity actually varies


def test_persistent_gain_same_balance_every_seed_fresh_varies():
    task = _gain_scenario()
    persistent = counterfactual_recovery(task, list(CONFIGS),
                                         fault_mode="persistent",
                                         seeds=(0, 1, 2))
    balances = {entry.runs[s].final_state["ledger"]["acct:ops"]
                for entry in persistent.strategies.values()
                for s in range(3)}
    assert balances == {200}  # factor 2, every seed, every strategy
    fresh = counterfactual_recovery(task, list(CONFIGS), fault_mode="fresh",
                                    seeds=(0, 1, 2))
    fresh_balances = {entry.runs[s].final_state["ledger"]["acct:ops"]
                      for entry in fresh.strategies.values()
                      for s in range(3)}
    assert fresh_balances == {200, 300}  # factors 2 and 3 across seeds


def test_fresh_fail_times_can_defeat_bounded_retry():
    # Persistent timeout (fail_times=1) is recovered by every
    # retrying strategy. Fresh draws fail_times up to 3, which a
    # max_retries of 2 cannot survive: recovery drops.
    task = SCENARIOS["timeout-01"]
    persistent = counterfactual_recovery(task, list(CONFIGS),
                                         fault_mode="persistent",
                                         seeds=(0, 1, 2))
    fresh = counterfactual_recovery(task, list(CONFIGS), fault_mode="fresh",
                                    seeds=(0, 1, 2))
    assert persistent.strategies["retry-only"].recovery_rate() == 1.0
    assert fresh.strategies["retry-only"].recovery_rate() < 1.0
    assert fresh.strategies["state-aware"].recovery_rate() < 1.0


def test_invalid_fault_mode_rejected():
    with pytest.raises(ValueError):
        counterfactual_recovery(SCENARIOS["timeout-01"], list(CONFIGS),
                                fault_mode="random")


# -- correction helps vs hurts ----------------------------------------

def test_retry_only_hurts_on_duplicate_delivery():
    # Baseline does not retry, so it completes once and recovers
    # by luck. Retry-only retries the completed transfer and
    # duplicates it: its correction makes the outcome worse.
    result = counterfactual_recovery(SCENARIOS["duplicate-01"],
                                     list(CONFIGS), fault_mode="persistent",
                                     seeds=(0, 1, 2))
    assert result.strategies["baseline"].recovered == 3
    assert result.strategies["retry-only"].recovered == 0
    assert result.strategies["retry-only"].hurts == 3
    assert result.strategies["retry-only"].helps == 0
    # The verifying strategies recover and do no harm.
    assert result.strategies["state-aware"].recovered == 3
    assert result.strategies["state-aware"].hurts == 0
    assert result.strategies["state-aware"].helps == 0


def test_retry_only_helps_on_timeout():
    result = counterfactual_recovery(SCENARIOS["timeout-01"],
                                     list(CONFIGS), fault_mode="persistent",
                                     seeds=(0, 1, 2))
    assert result.strategies["baseline"].recovered == 0
    for name in ("retry-only", "state-aware", "policy-constrained"):
        entry = result.strategies[name]
        assert entry.recovered == 3, name
        assert entry.helps == 3, name
        assert entry.hurts == 0, name


def test_no_fault_task_is_neutral_for_every_strategy():
    # With no disturbance there is nothing to correct, and no
    # strategy does worse than the baseline.
    result = counterfactual_recovery(SCENARIOS["benign-01"], list(CONFIGS),
                                     fault_mode="persistent", seeds=(0, 1, 2))
    for entry in result.strategies.values():
        assert entry.helps == 0 and entry.hurts == 0
        assert entry.task_completed == 3


# -- hindsight replanning ----------------------------------------------

def test_hindsight_replan_reaches_the_goal_under_another_strategy():
    failed = run_scenario(SCENARIOS["duplicate-01"],
                          CONFIG_BY_NAME["retry-only"], seed=0)
    assert not failed.recovered
    result = hindsight_replan(SCENARIOS["duplicate-01"], failed,
                              list(CONFIGS), fault_mode="persistent")
    assert result.failed_config == "retry-only"
    assert result.failed_seed == 0
    # A different plan for the same event reaches the goal.
    assert "state-aware" in result.reached_goal
    assert "policy-constrained" in result.reached_goal
    assert "baseline" in result.reached_goal
    assert "retry-only" not in result.reached_goal
    # Re-attempting under the same strategy reproduces the failure.
    assert result.same_strategy_reproduces is True


def test_hindsight_replan_reports_an_unrecoverable_failure():
    # No strategy recovers from an unavailable tool; the replan
    # reaches the goal under no strategy.
    failed = run_scenario(SCENARIOS["unavailable-01"],
                          CONFIG_BY_NAME["baseline"], seed=0)
    assert not failed.recovered
    result = hindsight_replan(SCENARIOS["unavailable-01"], failed,
                              list(CONFIGS), fault_mode="persistent")
    assert result.reached_goal == []
    assert result.same_strategy_reproduces is True


def test_hindsight_replan_refuses_a_recovered_run():
    recovered = run_scenario(SCENARIOS["timeout-01"],
                             CONFIG_BY_NAME["state-aware"], seed=0)
    assert recovered.recovered
    with pytest.raises(ValueError):
        hindsight_replan(SCENARIOS["timeout-01"], recovered, list(CONFIGS))


def test_hindsight_replan_reproduces_the_paired_runs():
    # The re-attempt is an exact replay: it matches the paired
    # runs the study already computed for the same seed.
    result = counterfactual_recovery(SCENARIOS["stale-01"], list(CONFIGS),
                                     fault_mode="persistent", seeds=(0,))
    failed = result.strategies["baseline"].runs[0]
    assert not failed.recovered
    replan = hindsight_replan(SCENARIOS["stale-01"], failed, list(CONFIGS),
                              fault_mode="persistent")
    for name, entry in result.strategies.items():
        assert (replan.attempts[name].to_dict()
                == entry.runs[0].to_dict()), name


# -- the shipped tasks are untouched ------------------------------------

def test_no_shipped_task_uses_gain_or_changed():
    assert len(SCENARIOS) == 17
    for scenario in SCENARIOS.values():
        for spec in scenario.faults.values():
            assert spec["fault"] in OLD_FAULTS, scenario.id
        assert scenario.version == "1.0"


def test_counterfactual_result_is_json_serialisable():
    result = counterfactual_recovery(SCENARIOS["timeout-01"], list(CONFIGS),
                                     fault_mode="persistent", seeds=(0,))
    json.dumps(result.to_dict())
    failed = result.strategies["baseline"].runs[0]
    json.dumps(hindsight_replan(SCENARIOS["timeout-01"], failed,
                                list(CONFIGS)).to_dict())


# -- study-level aggregation -------------------------------------------

def test_study_summary_structure_and_delta():
    study = run_counterfactual_study(
        [SCENARIOS["timeout-01"], SCENARIOS["duplicate-01"]],
        list(CONFIGS), seeds=(0, 1, 2))
    summary = study["summary"]
    assert summary["tasks"] == 2
    assert summary["runs"] == 2 * 4 * 3 * 2
    for name, metrics in summary["configs"].items():
        assert metrics["recovery_delta"] == pytest.approx(
            metrics["fresh_recovery_rate"]
            - metrics["persistent_recovery_rate"])
    # Fresh fail_times=3 defeats bounded retry on timeout-01, so
    # the retrying strategies lose recovery in fresh mode.
    assert summary["configs"]["retry-only"]["recovery_delta"] < 0
    # Hindsight: the retry-only duplicate failures are recoverable
    # under another strategy; the unavailable-style failures are not
    # present here, so every replanned failure reached the goal
    # under some strategy.
    assert summary["hindsight"]["failed_runs_replanned"] > 0
    assert summary["hindsight"]["same_strategy_reproduces_rate"] == 1.0
