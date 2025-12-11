"""Scoring: aggregate run results into comparable metrics.

Rates are fractions over the runs they apply to. Every metric is
computed from the run results by a rule written here — no LLM judge
is used anywhere, and no score is inferred after the fact: each
scenario's ``expected`` lists, ``expected_final_state`` and fault
schedule are defined in the scenario file before it runs.

- task success rate: runs where every ``must_complete`` action
  completed *and* the final state matches the expected final
  state. A run that completed the actions but left the system in
  the wrong state (a duplicate transfer, a held reservation) does
  not count.
- recovery success rate: runs where a fault fired, the task
  completed, and there were no duplicate actions and no unintended
  side effects and the final state matches. This is the study's
  central distinction: a run that completed the task *with* a
  duplicate or a side effect is "continued with side effects",
  not a recovery. The denominator is runs where a fault fired.
- continued-with-side-effects rate: runs where a fault fired, the
  task completed, but the run has duplicates or unintended side
  effects or a state mismatch.
- clean-abort rate: runs where the task failed, but cleanly — no
  duplicates, no unintended side effects, and the final state is
  the initial state (rolled back) or the expected state.
- duplicates per run / unintended side effects per run: means over
  all runs of the configuration.
- mean tool calls / mean retries: tool-call overhead of each
  strategy, including verification reads.
- mean approvals requested / denied: how often the human approval
  gate was consulted and how often it said no.
- budget-exceeded runs: runs stopped by the action budget.
- run-to-run consistency: for each scenario, the share of
  trial-pairs (across seeds) that agree on the outcome tuple
  (task_completed, recovered, duplicates present), averaged over
  scenarios. Deterministic policies score 1.0 here by construction;
  the meaningful variability in this study is across fault classes
  and strategies, reported per fault class below.
- recovery rate (ARSB-compatible name): the same quantity as
  recovery success rate, kept so RACRS numbers compare directly
  with ARSB's tool-error-recovery recovery rate.
"""

from __future__ import annotations

from itertools import combinations

from .runner import RunResult


def _rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _mean(values: list) -> float:
    return sum(values) / len(values) if values else 0.0


def _outcome(result: RunResult) -> tuple:
    return (result.task_completed, result.recovered,
            bool(result.duplicates))


def _pair_agreement(outcomes: list) -> float:
    pairs = list(combinations(outcomes, 2))
    if not pairs:
        return 1.0
    return sum(1 for a, b in pairs if a == b) / len(pairs)


def _by_category(subset: list[RunResult]) -> dict:
    out = {}
    for category in sorted({r.category for r in subset}):
        rows = [r for r in subset if r.category == category]
        faulted = [r for r in rows if r.faults_fired]
        out[category] = {
            "scenarios": len({r.scenario_id for r in rows}),
            "runs": len(rows),
            "task_success_rate": _rate(
                sum(1 for r in rows if r.task_completed), len(rows)),
            "recovery_success_rate": _rate(
                sum(1 for r in faulted if r.recovered), len(faulted)),
            "continued_with_side_effects_rate": _rate(
                sum(1 for r in faulted
                    if r.recovery_outcome == "continued-with-side-effects"),
                len(faulted)),
            "clean_abort_rate": _rate(
                sum(1 for r in rows if r.clean_abort), len(rows)),
            "duplicates_per_run": _mean([len(r.duplicates) for r in rows]),
            "unintended_per_run": _mean(
                [len(r.unintended_side_effects) for r in rows]),
            "mean_tool_calls": _mean([r.tool_calls for r in rows]),
        }
    return out


def _by_fault(subset: list[RunResult]) -> dict:
    out = {}
    for fault in sorted({f for r in subset for f in r.faults_fired}):
        rows = [r for r in subset if fault in r.faults_fired]
        out[fault] = {
            "runs": len(rows),
            "task_success_rate": _rate(
                sum(1 for r in rows if r.task_completed), len(rows)),
            "recovery_success_rate": _rate(
                sum(1 for r in rows if r.recovered), len(rows)),
            "duplicates_per_run": _mean([len(r.duplicates) for r in rows]),
            "unintended_per_run": _mean(
                [len(r.unintended_side_effects) for r in rows]),
            "mean_tool_calls": _mean([r.tool_calls for r in rows]),
        }
    return out


def score(results: list[RunResult]) -> dict:
    """Aggregate metrics per configuration, per category, per fault."""
    by_config: dict[str, dict] = {}
    configs = sorted({r.config for r in results})
    for config in configs:
        subset = [r for r in results if r.config == config]
        faulted = [r for r in subset if r.faults_fired]
        by_scenario: dict[str, list] = {}
        for r in subset:
            by_scenario.setdefault(r.scenario_id, []).append(_outcome(r))
        consistency = ([_pair_agreement(outcomes)
                        for outcomes in by_scenario.values()]
                       or [1.0])
        by_config[config] = {
            "scenarios": len({r.scenario_id for r in subset}),
            "runs": len(subset),
            "task_success_rate": _rate(
                sum(1 for r in subset if r.task_completed), len(subset)),
            "recovery_success_rate": _rate(
                sum(1 for r in faulted if r.recovered), len(faulted)),
            "recovery_rate": _rate(
                sum(1 for r in faulted if r.recovered), len(faulted)),
            "continued_with_side_effects_rate": _rate(
                sum(1 for r in faulted
                    if r.recovery_outcome == "continued-with-side-effects"),
                len(faulted)),
            "clean_abort_rate": _rate(
                sum(1 for r in subset if r.clean_abort), len(subset)),
            "duplicates_per_run": _mean([len(r.duplicates) for r in subset]),
            "duplicate_action_runs": sum(
                1 for r in subset if r.duplicates),
            "unintended_per_run": _mean(
                [len(r.unintended_side_effects) for r in subset]),
            "mean_tool_calls": _mean([r.tool_calls for r in subset]),
            "mean_retries": _mean([r.retries for r in subset]),
            "mean_approvals_requested": _mean(
                [r.approvals_requested for r in subset]),
            "mean_approvals_denied": _mean(
                [r.approvals_denied for r in subset]),
            "budget_exceeded_runs": sum(
                1 for r in subset if r.budget_exceeded),
            "state_match_rate": _rate(
                sum(1 for r in subset if r.state_matches), len(subset)),
            "run_to_run_consistency": (
                sum(consistency) / len(consistency)),
            "by_category": _by_category(subset),
            "by_fault": _by_fault(subset),
        }
    return {"configs": by_config, "total_runs": len(results)}
