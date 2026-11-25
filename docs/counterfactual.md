# Counterfactual recovery

## The question, borrowed

"Counterfactual World Models: JEPAs That Reason About 'What If'"
(Balestriero & LeCun, arXiv:2611.24778) asks: what would have
happened under a different action in the same event, with the
same hidden disturbance? The paper asks it about physical world
models and answers it with residual reuse — keep the observed
outcome, which carries the realised disturbance, and add only
the model's predicted action contrast. That formula does not
transfer here and is not implemented; the paper's code is not
used either. The inspiration is the question and the fault
taxonomy, not the mechanism.

This module answers the same question by paired re-runs. The
simulator is deterministic under a fixed seed, so the same task
can be replayed with the same fault schedule under a different
strategy, and the outcomes compared directly. No counterfactual
data, no extra parameters, no retraining — the same runner, the
same task, a different strategy. A difference between strategies
on a paired run is a difference in the strategy, not in the task
or the fault: the event is held fixed, only the action changes.
That is also the limit: it works because the world here is a
simulator we can rewind. A real deployment cannot be rewound,
which is exactly the problem the paper's formula addresses.

In recovery terms the question becomes three concrete ones:

1. Would this strategy have recovered on this exact fault, where
   another did not? (Per-task paired comparison.)
2. Does the recovery depend on the fault staying the same?
   (Persistent vs fresh faults.)
3. Did the correction help, or did it make the outcome worse?
   (Helps vs hurts — the local version of the paper's
   "correcting on noise" result.)

## Persistent vs fresh faults

`counterfactual_recovery(task, strategies, fault_mode, seeds)`
runs one task under every strategy. Two fault modes:

- `persistent`: the task's own fault schedule, identical on
  every run. Same fault, same severity, every time.
- `fresh`: a new schedule per seed from a seeded generator —
  same fault kind on the same action, fresh severity (a new
  `fail_times` of 1–3 for a failing or observation fault, a new
  `factor` of 2 or 3 for a `gain` fault). Fresh is still
  reproducible: the same (task, seed) always draws the same
  fresh schedule.

Measured on all 17 tasks x 4 strategies x seeds 0, 1, 2 (408
paired runs; recovery rate over runs where a fault fired):

| Configuration | Persistent | Fresh | Delta |
|---|---|---|---|
| baseline | 7.1% | 7.1% | 0.0 pp |
| retry-only | 28.6% | 11.9% | -16.7 pp |
| state-aware | 71.4% | 40.5% | -31.0 pp |
| policy-constrained | 71.4% | 40.5% | -31.0 pp |

Persistent mode reproduces the published study exactly (same
schedules, same numbers). Fresh mode is the stress test, and it
bites: a fresh `fail_times` of 3 defeats a bounded retry budget
of 2, so timeout-01 drops by two thirds and multi-01 — two
faults, both drawn at severity 3 — drops to zero for every
retrying strategy. The recovery the study measures depends
heavily on faults being single-shot; severity 3 breaks bounded
retry. Faults whose severity does not matter (`unavailable`,
`duplicate`, confirmation, partial failure, rollback) show no
delta. The finding is about the strategies, not the faults: a
strategy that only recovers when the fault is identical every
time is recovering from a known fault, not from faults in
general.

## Offset vs gain

The paper's fault taxonomy separates additive from
multiplicative disturbances: an offset fault adds a fixed error,
a gain fault multiplies the command. The study's existing faults
are the additive end. `gain` is the multiplicative end, added
as a new fault value (`{"fault": "gain", "factor": 2}`):

- A ledger transfer moves `amount * factor`; an inventory
  reserve/order takes `qty * factor`.
- A balance/stock read reports a scaled value.
- The call completes — the fault is in what it did, not in
  whether it ran — and it applies for `fail_times` attempts.
- Actions with no scalable quantity are unaffected.

A retry cannot fix a gain fault: the wrong amount is already
moved. On a hand-built transfer task with a factor-2 gain, every
strategy fails in both modes — the expected final state is
broken the moment the scaled transfer lands, and the retry
replays idempotently instead of moving more money. Only a
compensation (a refund of the scaled amount) or a clean abort
can undo it. That is the point of the class: it separates
"retry fixes this" from "only undo fixes this", which no
existing fault class does.

## Correction helps vs hurts

Each strategy is compared with the no-retry baseline on the
identical fault and seed. `helps`: the strategy recovered where
the baseline did not. `hurts`: the baseline recovered (or
completed cleanly) and the strategy did worse — it failed, or
its correction added a duplicate or a side effect the baseline
avoided. Totals over both modes (96 fault-firing runs per
strategy):

| Configuration | Helps | Hurts |
|---|---|---|
| baseline | 0 | 0 |
| retry-only | 17 | 6 |
| state-aware | 41 | 0 |
| policy-constrained | 41 | 6 |

The two hurts cases are the study's known ones, now counted
per event instead of averaged away. Retry-only's 6 hurts are
duplicate-01 in both modes: the baseline completes once and
recovers by luck, retry-only retries the completed transfer and
duplicates it — its correction makes the outcome worse.
Policy-constrained's 6 hurts are confirmation-01 in both modes:
the baseline completes the large payment, the approval gate
denies it — the gate's cost, stated as a per-event harm rather
than a headline rate. State-aware has 41 helps and 0 hurts: it
never does worse than doing nothing. With no fault at all
(benign-01) every strategy is neutral: nothing to correct,
nothing harmed.

## Hindsight replanning

`hindsight_replan(task, failed_run, strategies)` re-attempts a
failed run under different recovery policies — same task, same
fault schedule, same seed — and reports which re-attempts reach
the goal. "Replan" here means a different recovery policy for
the same event: the plan steps are fixed by the scenario, the
policy is what changes. Re-attempting under the *same* strategy
reproduces the failure exactly, and that reproduction is
reported as a control: a deterministic agent that replans
identically gains nothing; the gain has to come from a different
plan.

Over the full study, 219 failed runs were replanned:

- 71 reached the goal under some other strategy — the failure
  was recoverable, the first plan was the problem.
- 148 reached the goal under no strategy — the failure was in
  the event, not the plan (an unavailable tool, a gain fault,
  a confirmation the gate will always deny).
- Same-strategy reproduction rate: 1.0 — every re-attempt under
  the failed run's own strategy reproduced the same outcome.
  The counterfactual is identified by replay, not estimated.

## How to run it

```python
from racrs.agents import CONFIGS
from racrs.counterfactual import (
    counterfactual_recovery, hindsight_replan,
    run_counterfactual_study)
from racrs.scenario import Scenario

scenarios = Scenario.load_all("scenarios")
# One task, both modes:
result = counterfactual_recovery(scenarios[1], list(CONFIGS),
                                 fault_mode="persistent", seeds=(0, 1, 2))
print(result.strategies["state-aware"].recovery_rate())
# The whole study, with hindsight replans for every failed run:
study = run_counterfactual_study(scenarios, seeds=(0, 1, 2))
print(study["summary"]["configs"]["state-aware"]["recovery_delta"])
print(study["summary"]["hindsight"])
```

## Limits

- The paper has no rollbacks, compensations or idempotency:
  those remain this project's own machinery, and the hindsight
  result depends on them. A replan that reaches the goal under
  state-aware does so because that strategy verifies and
  compensates, not because of anything in the paper.
- The paired answer is exact only because the simulator is
  deterministic under a fixed seed. A model-backed agent behind
  the same interface is not deterministic even at temperature 0,
  so its paired runs are approximate: the same seed does not
  guarantee the same event.
- Fresh severity is a draw, not a dial. The paper interpolates
  an offset fault into a pure gain fault with a parameter lambda;
  this module has the two ends (the existing faults and `gain`)
  but no graded lambda between them.
- One task per fault class, as in the main study: the fresh-mode
  deltas are a worked example per class, not a statistically
  powered estimate.
- `gain` is exercised by the counterfactual module's tests only.
  No shipped task uses it, and the published 17-task results
  still cover the original seven fault classes.
