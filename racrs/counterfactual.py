"""Counterfactual recovery: paired re-runs of the same task under the same fault.

The question is borrowed from "Counterfactual World Models: JEPAs
That Reason About 'What If'" (Balestriero & LeCun,
arXiv:2611.24778): what would have happened under a different
action in the same event, with the same hidden disturbance? The
paper asks it about physical world models and answers it with
residual reuse — keep the observed outcome, which carries the
realised disturbance, and add only the model's predicted action
contrast. That formula does not transfer here and is not
implemented; the paper's code is not used either. This module
answers the same question a different way, by paired re-runs:
the simulator is deterministic under a fixed seed, so the same
task can be replayed with the same fault schedule under a
different strategy, and the outcomes compared directly. No
counterfactual data, no extra parameters, no retraining — the
same runner, the same task, a different strategy. That is the
whole mechanism, and it is also its limit: it works because the
world here is a simulator we can rewind. A real deployment cannot
be rewound, which is exactly the problem the paper's formula
addresses.

What the module reports, per task:

- Which strategies recover on the identical fault: the same task,
  the same fault schedule, the same seed, run under each of the
  four strategies. A difference between strategies on that run
  is a difference in the strategy, not in the task or the fault —
  the event is held fixed, only the action changes.
- Persistent vs fresh faults. ``persistent`` replays the identical
  fault schedule on every run: the same fault, the same severity,
  every time. ``fresh`` draws a new schedule per seed from a
  seeded generator — same fault kind on the same action, fresh
  severity (a new ``fail_times`` for a failing fault, a new
  ``factor`` for a ``gain`` fault). The recovery-rate delta
  between the two modes says whether a strategy's recovery
  depends on the fault staying the same: a strategy that only
  recovers when the fault is identical every time is recovering
  from a known fault, not from faults in general.
- Correction helps vs hurts. Each strategy is compared with the
  no-retry baseline on the identical fault and seed. ``helps``:
  the strategy recovered where the baseline did not. ``hurts``:
  the baseline recovered (or completed cleanly) and the strategy
  did worse — it failed, or its retry/compensation added a
  duplicate or a side effect the baseline avoided. This is the
  local version of the paper's "correcting on noise" result: a
  correction applied where nothing is wrong to correct makes the
  outcome worse, and it is counted, not averaged away.
- Hindsight replanning. After a failed run, the same task is
  re-attempted with the same fault and seed under a different
  recovery policy, and the module reports whether the new plan
  reaches the goal. "Replan" here means a different recovery
  policy for the same event: the plan steps are fixed by the
  scenario, the policy is what changes. Re-attempting under the
  *same* strategy reproduces the failure exactly — a deterministic
  agent that replans identically gains nothing; the gain has to
  come from a different plan. That reproduction is reported too,
  as a control.

The ``gain`` fault class (see ``tools.py``) is the paper's
offset-vs-gain distinction in miniature: an offset fault adds a
fixed error, a gain fault multiplies the command. The existing
faults are the additive end; ``gain`` is the multiplicative end.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field, replace

from .agents import CONFIGS, AgentConfig
from .runner import RunResult, run_scenario
from .scenario import Scenario

FAULT_MODES = ("persistent", "fresh")

# Fault kinds whose severity a fresh draw varies by fail_times.
# "gain" varies by factor instead (see fresh_schedule).
_GAIN_FACTORS = (2, 3)


def fresh_schedule(task: Scenario, seed: int) -> dict:
    """Draw a fresh fault schedule for one re-run of ``task``.

    Same fault kind on the same action, fresh severity: a new
    ``fail_times`` (1-3) for a failing or observation fault, a new
    ``factor`` (2 or 3) for a ``gain`` fault. The draw is seeded
    on the task id and the seed, so the same (task, seed) always
    draws the same fresh schedule — a fresh fault is still a
    reproducible fault. The original task is never modified: the
    caller replaces the schedule on a copy of the scenario.
    """
    rng = random.Random(f"counterfactual-fresh:{task.id}:{seed}")
    fresh = {}
    for key, spec in task.faults.items():
        new = dict(spec)
        if spec.get("fault") == "gain":
            new["factor"] = rng.choice(_GAIN_FACTORS)
        else:
            new["fail_times"] = rng.randint(1, 3)
        fresh[key] = new
    return fresh


def _verdict(run: RunResult, baseline_run: RunResult) -> str:
    """helps / hurts / neutral for one paired run.

    ``helps``: the strategy recovered where the no-retry baseline
    did not. ``hurts``: the baseline recovered (or completed
    cleanly) and the strategy did worse — it failed, or its
    correction added a duplicate or a side effect the baseline
    avoided. Anything else is ``neutral``: the same outcome
    either way.
    """
    if run.recovered and not baseline_run.recovered:
        return "helps"
    if baseline_run.recovered and not run.recovered:
        return "hurts"
    run_harm = bool(run.duplicates or run.unintended_side_effects)
    base_harm = bool(baseline_run.duplicates
                     or baseline_run.unintended_side_effects)
    if run_harm and not base_harm:
        return "hurts"
    if baseline_run.task_completed and not run.task_completed:
        return "hurts"
    return "neutral"


@dataclass
class StrategyCounterfactual:
    """One strategy's paired runs on one task in one fault mode."""

    config: str
    fault_mode: str
    runs: list = field(default_factory=list)  # one RunResult per seed
    recovered: int = 0
    task_completed: int = 0
    duplicates: int = 0
    helps: int = 0
    hurts: int = 0
    neutral: int = 0

    def recovery_rate(self) -> float:
        """Recoveries over runs where a fault fired (0.0 if none did)."""
        fault_runs = [r for r in self.runs if r.faults_fired]
        if not fault_runs:
            return 0.0
        return sum(1 for r in fault_runs if r.recovered) / len(fault_runs)

    def to_dict(self) -> dict:
        return {
            "config": self.config, "fault_mode": self.fault_mode,
            "runs": [r.to_dict() for r in self.runs],
            "recovered": self.recovered,
            "task_completed": self.task_completed,
            "duplicates": self.duplicates,
            "helps": self.helps, "hurts": self.hurts,
            "neutral": self.neutral,
            "recovery_rate": self.recovery_rate(),
        }


@dataclass
class CounterfactualResult:
    """Paired re-runs of one task under every strategy, one fault mode."""

    scenario_id: str
    category: str
    fault_mode: str
    strategies: dict = field(default_factory=dict)  # name -> StrategyCounterfactual
    seeds: list = field(default_factory=list)
    baseline_present: bool = False

    def recovery_rate(self, config: str) -> float:
        return self.strategies[config].recovery_rate()

    def to_dict(self) -> dict:
        return {
            "scenario_id": self.scenario_id, "category": self.category,
            "fault_mode": self.fault_mode, "seeds": list(self.seeds),
            "baseline_present": self.baseline_present,
            "strategies": {name: s.to_dict()
                           for name, s in self.strategies.items()},
        }


@dataclass
class HindsightResult:
    """Re-attempts of one failed run under different recovery policies.

    ``attempts`` maps each strategy name to its re-attempt on the
    same task, same fault schedule and same seed. ``reached_goal``
    lists the strategies whose re-attempt completed the task.
    ``same_strategy_reproduces`` is True when re-attempting under
    the failed run's own strategy reproduces the same recovery
    outcome — the determinism control: an identical replan gains
    nothing, so any gain in ``reached_goal`` comes from a
    different plan, not from a different roll of the dice.
    """

    scenario_id: str
    failed_config: str
    failed_seed: int
    fault_mode: str
    attempts: dict = field(default_factory=dict)  # name -> RunResult
    reached_goal: list = field(default_factory=list)
    same_strategy_reproduces: bool | None = None

    def to_dict(self) -> dict:
        return {
            "scenario_id": self.scenario_id,
            "failed_config": self.failed_config,
            "failed_seed": self.failed_seed,
            "fault_mode": self.fault_mode,
            "attempts": {name: r.to_dict()
                         for name, r in self.attempts.items()},
            "reached_goal": list(self.reached_goal),
            "same_strategy_reproduces": self.same_strategy_reproduces,
        }


def counterfactual_recovery(task: Scenario, strategies=None, *,
                            fault_mode: str = "persistent",
                            seeds: tuple[int, ...] = (0, 1, 2)
                            ) -> CounterfactualResult:
    """Run the same task with the same fault under every strategy.

    ``fault_mode`` is ``"persistent"`` (the task's own fault
    schedule, identical on every run) or ``"fresh"`` (a new
    schedule per seed from :func:`fresh_schedule`). ``seeds`` are
    the paired seeds: the same seed is used for every strategy,
    so each seed is one event replayed under different policies.
    The input task is never modified; fresh mode runs on a copy
    with a replaced schedule.
    """
    if fault_mode not in FAULT_MODES:
        raise ValueError(f"unknown fault_mode {fault_mode!r}; "
                         f"expected one of {FAULT_MODES}")
    strategies = list(strategies) if strategies is not None else list(CONFIGS)
    if not strategies:
        raise ValueError("at least one strategy is required")
    seeds = tuple(seeds)
    per_config: dict[str, list[RunResult]] = {}
    for config in strategies:
        runs = []
        for seed in seeds:
            scenario = task
            if fault_mode == "fresh":
                scenario = replace(
                    task, fault_schedule=fresh_schedule(task, seed))
            runs.append(run_scenario(scenario, config, seed=seed))
        per_config[config.name] = runs
    baseline_runs = {r.seed: r for r in per_config.get("baseline", [])}
    out: dict[str, StrategyCounterfactual] = {}
    for config in strategies:
        runs = per_config[config.name]
        helps = hurts = neutral = 0
        for run in runs:
            verdict = "neutral"
            if config.name != "baseline" and run.seed in baseline_runs:
                verdict = _verdict(run, baseline_runs[run.seed])
            if verdict == "helps":
                helps += 1
            elif verdict == "hurts":
                hurts += 1
            else:
                neutral += 1
        out[config.name] = StrategyCounterfactual(
            config=config.name, fault_mode=fault_mode, runs=runs,
            recovered=sum(1 for r in runs if r.recovered),
            task_completed=sum(1 for r in runs if r.task_completed),
            duplicates=sum(len(r.duplicates) for r in runs),
            helps=helps, hurts=hurts, neutral=neutral)
    return CounterfactualResult(
        scenario_id=task.id, category=task.category,
        fault_mode=fault_mode, strategies=out, seeds=list(seeds),
        baseline_present="baseline" in per_config)


def hindsight_replan(task: Scenario, failed: RunResult, strategies=None, *,
                     fault_mode: str = "persistent",
                     seed: int | None = None) -> HindsightResult:
    """Re-attempt a failed run under different recovery policies.

    ``failed`` is a run that did not recover (a run that recovered
    needs no replan). The same task is re-attempted with the same
    fault schedule and the same seed under each strategy — the
    replan is a different recovery policy for the same event, not
    a different event. In ``fresh`` mode the schedule is the one
    drawn for the failed run's seed, recomputed deterministically.
    Returns which strategies' re-attempts reach the goal.
    """
    if failed.recovered:
        raise ValueError("hindsight_replan needs a run that did not "
                         "recover; this one did")
    if fault_mode not in FAULT_MODES:
        raise ValueError(f"unknown fault_mode {fault_mode!r}; "
                         f"expected one of {FAULT_MODES}")
    strategies = list(strategies) if strategies is not None else list(CONFIGS)
    if not strategies:
        raise ValueError("at least one strategy is required")
    seed = failed.seed if seed is None else seed
    scenario = task
    if fault_mode == "fresh":
        scenario = replace(task, fault_schedule=fresh_schedule(task, seed))
    attempts = {}
    for config in strategies:
        attempts[config.name] = run_scenario(scenario, config, seed=seed)
    reached = [name for name, result in attempts.items()
               if result.task_completed]
    same = None
    if failed.config in attempts:
        same = (attempts[failed.config].recovery_outcome
                == failed.recovery_outcome)
    return HindsightResult(
        scenario_id=task.id, failed_config=failed.config,
        failed_seed=failed.seed, fault_mode=fault_mode,
        attempts=attempts, reached_goal=reached,
        same_strategy_reproduces=same)


def _rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def run_counterfactual_study(scenarios, strategies=None, *,
                             seeds: tuple[int, ...] = (0, 1, 2)) -> dict:
    """Run every task in both fault modes, with hindsight replans.

    Returns ``{"results", "hindsight", "summary"}``. ``results``
    maps each scenario id to its persistent and fresh
    :class:`CounterfactualResult`. ``hindsight`` holds one
    :class:`HindsightResult` per failed run that fired a fault
    (both modes). ``summary`` aggregates per configuration the
    recovery rate in each mode and the delta (fresh minus
    persistent), the helps/hurts totals, and the hindsight totals:
    how many failed runs reached the goal under some other
    strategy, and how many under no strategy at all.
    """
    strategies = list(strategies) if strategies is not None else list(CONFIGS)
    seeds = tuple(seeds)
    results: dict[str, dict[str, CounterfactualResult]] = {}
    hindsight: list[HindsightResult] = []
    for task in scenarios:
        entry = {}
        for mode in FAULT_MODES:
            entry[mode] = counterfactual_recovery(
                task, strategies, fault_mode=mode, seeds=seeds)
        results[task.id] = entry
        for mode in FAULT_MODES:
            for config in strategies:
                for run in entry[mode].strategies[config.name].runs:
                    if not run.recovered and run.faults_fired:
                        hindsight.append(hindsight_replan(
                            task, run, strategies, fault_mode=mode))
    summary: dict = {"tasks": len(scenarios), "seeds": list(seeds),
                     "runs": len(scenarios) * len(strategies) * len(seeds) * 2,
                     "configs": {}, "per_task": {},
                     "hindsight": {}}
    for config in strategies:
        name = config.name
        per_mode: dict[str, dict] = {}
        for mode in FAULT_MODES:
            fault_runs = [r for task_id in results
                          for r in results[task_id][mode].strategies[name].runs
                          if r.faults_fired]
            recovered = sum(1 for r in fault_runs if r.recovered)
            per_mode[mode] = {
                "fault_runs": len(fault_runs),
                "recovered": recovered,
                "recovery_rate": _rate(recovered, len(fault_runs)),
                "helps": sum(results[t][mode].strategies[name].helps
                             for t in results),
                "hurts": sum(results[t][mode].strategies[name].hurts
                             for t in results),
                "neutral": sum(results[t][mode].strategies[name].neutral
                               for t in results),
            }
        summary["configs"][name] = {
            "persistent_recovery_rate": per_mode["persistent"]["recovery_rate"],
            "fresh_recovery_rate": per_mode["fresh"]["recovery_rate"],
            "recovery_delta": (per_mode["fresh"]["recovery_rate"]
                               - per_mode["persistent"]["recovery_rate"]),
            "persistent": per_mode["persistent"],
            "fresh": per_mode["fresh"],
        }
    for task_id, entry in results.items():
        summary["per_task"][task_id] = {
            name: {
                "persistent": entry["persistent"].recovery_rate(name),
                "fresh": entry["fresh"].recovery_rate(name),
                "delta": (entry["fresh"].recovery_rate(name)
                          - entry["persistent"].recovery_rate(name)),
            }
            for name in entry["persistent"].strategies
        }
    reached_some = sum(1 for h in hindsight if h.reached_goal)
    same_reproduces = [h.same_strategy_reproduces for h in hindsight
                       if h.same_strategy_reproduces is not None]
    summary["hindsight"] = {
        "failed_runs_replanned": len(hindsight),
        "reached_goal_under_some_strategy": reached_some,
        "reached_goal_under_no_strategy": len(hindsight) - reached_some,
        "same_strategy_reproduces_rate": _rate(
            sum(1 for v in same_reproduces if v), len(same_reproduces)),
    }
    return {"results": results, "hindsight": hindsight, "summary": summary}
