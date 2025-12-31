"""Scoring tests, including the recovery vs continued distinction."""

from racrs.runner import RunResult
from racrs.scoring import score


def _result(config, scenario_id="x-01", category="timeout", **overrides):
    base = dict(scenario_id=scenario_id, category=category, config=config,
                seed=0, task_completed=False, recovered=False,
                faults_fired=["timeout"])
    base.update(overrides)
    return RunResult(**base)


def test_recovery_requires_no_duplicates_or_side_effects():
    # Task completed with a duplicate is continued, not recovered.
    continued = _result("retry-only", task_completed=True, recovered=False,
                        duplicates=["ledger:transfer:acct:ops"],
                        recovery_outcome="continued-with-side-effects")
    metrics = score([continued])
    config = metrics["configs"]["retry-only"]
    assert config["recovery_success_rate"] == 0.0
    assert config["continued_with_side_effects_rate"] == 1.0
    assert config["task_success_rate"] == 1.0


def test_clean_recovery_counts():
    recovered = _result("state-aware", task_completed=True, recovered=True)
    failed = _result("state-aware", task_completed=False, recovered=False,
                     clean_abort=True)
    metrics = score([recovered, failed])
    config = metrics["configs"]["state-aware"]
    assert config["recovery_success_rate"] == 0.5
    assert config["clean_abort_rate"] == 0.5
    assert config["task_success_rate"] == 0.5


def test_no_fault_runs_excluded_from_recovery_denominator():
    benign = _result("baseline", scenario_id="benign-01", category="benign",
                     task_completed=True, faults_fired=[])
    metrics = score([benign])
    config = metrics["configs"]["baseline"]
    assert config["recovery_success_rate"] == 0.0  # no faulted runs
    assert config["task_success_rate"] == 1.0


def test_by_fault_and_duplicates_per_run():
    results = [
        _result("retry-only", scenario_id="a", task_completed=False,
                duplicates=["ledger:transfer:acct:ops"]),
        _result("retry-only", scenario_id="b", task_completed=True,
                recovered=True, duplicates=[]),
    ]
    metrics = score(results)
    config = metrics["configs"]["retry-only"]
    assert config["duplicates_per_run"] == 0.5
    assert config["duplicate_action_runs"] == 1
    assert config["by_fault"]["timeout"]["runs"] == 2
    assert config["by_fault"]["timeout"]["recovery_success_rate"] == 0.5


def test_run_to_run_consistency_agrees_on_identical_outcomes():
    results = [_result("baseline", seed=s, task_completed=True, recovered=True)
               for s in (0, 1, 2)]
    assert score(results)["configs"]["baseline"]["run_to_run_consistency"] == 1.0
    mixed = [_result("baseline", seed=0, task_completed=True, recovered=True),
             _result("baseline", seed=1, task_completed=False, recovered=False)]
    assert score(mixed)["configs"]["baseline"]["run_to_run_consistency"] == 0.0
