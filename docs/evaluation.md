# Evaluation

## Method

13 scenarios (version 1.0) x 4 agent configurations x seeds 0, 1, 2.
156 runs. Deterministic simulated agents; the same seeds reproduce
the same results (verified: two full runs produce identical
`report.json`). Full traces for the seed-0 runs: `examples/traces/`
(52 JSONL files). Reproduce with `python scripts/evaluate.py`.

## Headline results

| Configuration | Task success | Recovery success | Continued with side effects | Clean abort | Duplicates / run | Unintended / run | Mean tool calls | Mean retries | Mean approvals denied | State match |
|---|---|---|---|---|---|---|---|---|---|---|---|
| baseline | 30.8% | 10.0% | 0.0% | 15.4% | 0.23 | 0.00 | 2.7 | 0.00 | 0.00 | 30.8% |
| retry-only | 46.2% | 30.0% | 0.0% | 0.0% | 0.31 | 0.00 | 3.1 | 0.38 | 0.00 | 46.2% |
| state-aware | 76.9% | 70.0% | 0.0% | 23.1% | 0.00 | 0.00 | 3.8 | 0.54 | 0.00 | 76.9% |
| policy-constrained | 69.2% | 70.0% | 0.0% | 30.8% | 0.00 | 0.00 | 3.7 | 0.54 | 0.08 | 69.2% |

## Task success by category

| Category | baseline | retry-only | state-aware | policy-constrained |
|---|---|---|---|---|
| benign | 100.0% | 100.0% | 100.0% | 100.0% |
| confirmation | 100.0% | 100.0% | 100.0% | 50.0% |
| contradictory-observation | 0.0% | 0.0% | 100.0% | 100.0% |
| duplicate-delivery | 100.0% | 0.0% | 100.0% | 100.0% |
| incomplete-observation | 0.0% | 0.0% | 100.0% | 100.0% |
| malformed | 0.0% | 100.0% | 100.0% | 100.0% |
| multi-fault | 0.0% | 100.0% | 100.0% | 100.0% |
| partial-failure | 0.0% | 0.0% | 0.0% | 0.0% |
| rollback | 0.0% | 0.0% | 0.0% | 0.0% |
| stale-observation | 0.0% | 100.0% | 100.0% | 100.0% |
| timeout | 0.0% | 100.0% | 100.0% | 100.0% |
| unavailable | 0.0% | 0.0% | 0.0% | 0.0% |

## Recovery success by fault class

| Fault | baseline | retry-only | state-aware | policy-constrained |
|---|---|---|---|---|
| contradictory | 0.0% | 0.0% | 100.0% | 100.0% |
| duplicate | 100.0% | 0.0% | 100.0% | 100.0% |
| incomplete | 0.0% | 0.0% | 100.0% | 100.0% |
| malformed | 0.0% | 100.0% | 100.0% | 100.0% |
| stale | 0.0% | 0.0% | 100.0% | 100.0% |
| timeout | 0.0% | 100.0% | 100.0% | 100.0% |
| unavailable | 0.0% | 0.0% | 0.0% | 0.0% |

## Findings

1. **Retrying without verifying is worse than not retrying, for
   one fault class.** Retry-only is the only strategy that
   duplicates a delivery (0.31 duplicates per run, the highest of
   the four), and it scores 0.0% recovery on duplicate-delivery
   while the baseline — which never retries — scores 100.0%
   there. The retry is the bug, not the fix, when the error
   report follows a completed action.
2. **Verification, not retrying, is what fixes bad observations.**
   Retry-only and the baseline both score 0.0% on stale,
   incomplete and contradictory observations: neither ever
   detects the wrong value, so neither ever retries the read.
   State-aware and policy-constrained score 100.0% on all three,
   because the postcondition catches the wrong value and the
   retry fetches the true one. The retry count is the same
   (mean 0.54 retries per run for both verifying strategies);
   the difference is what triggers the retry.
3. **No strategy recovers from an unavailable tool, and none is
   expected to.** Recovery is 0.0% for every configuration on
   `unavailable`, on partial-failure and on rollback — those
   tasks cannot complete when a required tool is down. What
   differs is what is left behind: state-aware and
   policy-constrained abort cleanly (clean-abort rates 23.1%
   and 30.8%) by releasing reservations and refunding payments,
   while the baseline and retry-only leave a reservation held,
   money moved, or a receipt written for an unpaid order.
4. **The control / usefulness trade-off is one scenario wide.**
   Policy-constrained matches state-aware on recovery (70.0%)
   and on duplicates (0.00 per run), and beats it on clean abort
   (30.8% vs 23.1%), but its task success is lower (69.2% vs
   76.9%) because it blocks the large unapproved payment in
   confirmation-01. Below the threshold the same gate approves
   (confirmation-02 completes for every strategy).
5. **Overhead is small and attributable.** Mean tool calls rise
   from 2.7 (baseline) to 3.8 (state-aware): the extra calls are
   the verification reads (one per effectful step) and the
   retries. Mean approvals requested rise from 2.0 to 2.38 for
   retry-only, because each retry re-requests approval — a real
   cost of retrying without verifying.
6. **Run-to-run consistency is 100.0% for every strategy.** The
   policies are deterministic and the fault schedule is fixed per
   scenario, so repeated seeds reproduce the same runs. The
   variability in this study is across fault classes and
   strategies, not across seeds. That is a property of the
   simulated agents, not evidence about real models, whose
   run-to-run variability project 8 measures with seeded
   readings.

## Comparison with ARSB

ARSB's published numbers (37 scenarios v1.0 x 4 configs, seeds 0,
1, 2, 444 runs) are reference data, not measured here.

| Configuration | ARSB recovery | RACRS recovery success |
|---|---|---|
| baseline | 50.0% | 10.0% |
| hierarchy-aware | 75.0% | n/a (no ARSB equivalent) |
| tool-side-enforced | 75.0% | n/a (no ARSB equivalent) |
| cautious | 75.0% | n/a (no ARSB equivalent) |
| retry-only | n/a (no ARSB equivalent) | 30.0% |
| state-aware | n/a (no ARSB equivalent) | 70.0% |
| policy-constrained | n/a (no ARSB equivalent) | 70.0% |

The recovery rate is the same definition in both projects (task
completed after a fault, no duplicates), but the fault coverage
differs: ARSB measures it on 4 tool-error-recovery scenarios
(timeout, malformed, unavailable, duplicate), RACRS on 7 fault
classes plus partial failure, rollback and confirmation. The
baseline's drop from 50.0% to 10.0% is explained by that
coverage: in ARSB its only recovery was duplicate-delivery, and
in RACRS it also faces stale, incomplete and contradictory
observations, which it cannot detect. The comparison is a
definition check, not a ranking.

## Limitations

- **Simulated agents, not models.** Every result is about four
  hand-written decision policies. Nothing here measures any real
  language model; a model-backed adapter behind the same
  `AgentAdapter` interface would produce different numbers, and
  its run-to-run variability would be non-zero.
- **One scenario per fault class.** With 13 scenarios, each
  per-category rate is a single task repeated over 3 seeds. The
  headline rates are stable, but the per-category table should
  be read as a worked example per fault class, not as a
  statistically powered estimate.
- **Faults are scheduled, not emergent.** Faults fire at fixed
  points with fixed `fail_times`. Real tool failures are
  intermittent, correlated and sometimes partial in ways a
  schedule does not capture.
- **Compensations are pre-written.** Each plan step's undo action
  is stated in the scenario file. The study measures whether an
  agent *runs* its compensations, not whether it can *derive*
  them.
- **Continued-with-side-effects is unpopulated.** In this
  dataset every duplicate also breaks the final state, so the
  rate is 0.0% everywhere. The definition is kept (see
  `docs/methodology.md`); a scenario where a duplicate does not
  change the final state would be needed to exercise it.
- **The action budget is never reached.** No scenario comes
  close to the policy-constrained budget of 12 calls (mean 3.7).
  The budget is enforced and unit-tested, but its effect on
  task success is not measured by any scenario.
- **No human in the loop.** The approval gate's simulated
  approver grants only pre-approved actions (or amounts below
  the threshold). A real approver's judgement, delay and error
  rate are not modelled.

## Recommendations

1. Do not retry an error report without first checking whether
   the action completed — verify, then retry, or attach an
   idempotency key so a retry cannot re-execute.
2. Check a postcondition after every effectful step, not just
   after failures: the stale / incomplete / contradictory faults
   all present as successful calls with wrong observations.
3. Abort the plan and compensate when a step fails permanently;
   carrying on writes receipts for unpaid orders and leaves
   reservations held.
4. Put consequential actions behind an approval gate with a
   confirmation threshold, and pre-approve the task's
   compensations alongside its plan — otherwise a rollback the
   user did not authorise is itself a side effect.
