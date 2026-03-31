# Evaluation

## Method

17 scenarios (version 1.0) x 4 agent configurations x seeds 0, 1, 2.
204 runs. Deterministic simulated agents; the same seeds reproduce
the same results (verified: two full runs produce identical
`report.json`). Full traces for the seed-0 runs: `examples/traces/`
(68 JSONL files). Reproduce with `python scripts/evaluate.py`.

## Headline results

| Configuration | Task success | Recovery success | Continued with side effects | Clean abort | Duplicates / run | Unintended / run | Mean tool calls | Mean retries | Mean approvals denied | State match |
|---|---|---|---|---|---|---|---|---|---|---|---|
| baseline | 23.5% | 7.1% | 0.0% | 23.5% | 0.29 | 0.00 | 2.8 | 0.00 | 0.00 | 35.3% |
| retry-only | 41.2% | 28.6% | 0.0% | 5.9% | 0.35 | 0.00 | 3.1 | 0.35 | 0.00 | 47.1% |
| state-aware | 76.5% | 71.4% | 0.0% | 23.5% | 0.00 | 0.00 | 3.9 | 0.59 | 0.00 | 76.5% |
| policy-constrained | 70.6% | 71.4% | 0.0% | 29.4% | 0.00 | 0.00 | 3.8 | 0.59 | 0.06 | 70.6% |

## Task success by category

| Category | baseline | retry-only | state-aware | policy-constrained |
|---|---|---|---|---|
| benign | 100.0% | 100.0% | 100.0% | 100.0% |
| confirmation | 100.0% | 100.0% | 100.0% | 50.0% |
| contradictory-observation | 0.0% | 0.0% | 100.0% | 100.0% |
| delegation | 0.0% | 25.0% | 75.0% | 75.0% |
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
   duplicates a delivery (0.35 duplicates per run, the highest of
   the four), and it scores 0.0% recovery on duplicate-delivery
   while the baseline — which never retries — scores 100.0%
   there. The retry is the bug, not the fix, when the error
   report follows a completed action. The delegation tasks add
   two more ways to duplicate: a stale delegated quote and a
   contradictory delegated stock report both make the
   non-verifying strategies repeat the action (1.00 duplicates
   per run on the stale and contradictory faults for baseline
   and retry-only alike).
2. **Verification, not retrying, is what fixes bad observations.**
   Retry-only and the baseline both score 0.0% on stale,
   incomplete and contradictory observations: neither ever
   detects the wrong value, so neither ever retries the read.
   State-aware and policy-constrained score 100.0% on all three,
   because the postcondition catches the wrong value and the
   retry fetches the true one. The retry count is the same
   (mean 0.59 retries per run for both verifying strategies);
   the difference is what triggers the retry. The delegation
   tasks show the same split for delegated results: the
   verifying strategies score 75.0% task success on the
   delegation category (the fourth task cannot complete — see
   finding 3), the baseline 0.0%.
3. **No strategy recovers from an unavailable tool, and none is
   expected to.** Recovery is 0.0% for every configuration on
   `unavailable`, on partial-failure and on rollback — those
   tasks cannot complete when a required tool is down. What
   differs is what is left behind: state-aware and
   policy-constrained abort cleanly (clean-abort rates 23.5%
   and 29.4%) by releasing reservations and refunding payments,
   while the baseline and retry-only leave a reservation held,
   money moved, or a receipt written for an unpaid order. The
   delegation version sharpens the point: when the sub-agent is
   down, the verifying strategies refund the payment they
   already made (delegate-unavailable-01: the compensation
   runs, the final state is back to the starting state), while
   the others leave the payment in place and write a receipt
   for a payment nobody confirmed — and the clean-abort rate
   counts both as clean (see the limitation below).
4. **The control / usefulness trade-off is one scenario wide.**
   Policy-constrained matches state-aware on recovery (71.4%)
   and on duplicates (0.00 per run), and beats it on clean abort
   (29.4% vs 23.5%), but its task success is lower (70.6% vs
   76.5%) because it blocks the large unapproved payment in
   confirmation-01. Below the threshold the same gate approves
   (confirmation-02 completes for every strategy).
5. **Overhead is small and attributable.** Mean tool calls rise
   from 2.8 (baseline) to 3.9 (state-aware): the extra calls are
   the verification reads (one per effectful step) and the
   retries. Mean approvals requested rise from 2.0 to 2.29 for
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
| baseline | 50.0% | 7.1% |
| hierarchy-aware | 75.0% | n/a (no ARSB equivalent) |
| tool-side-enforced | 75.0% | n/a (no ARSB equivalent) |
| cautious | 75.0% | n/a (no ARSB equivalent) |
| retry-only | n/a (no ARSB equivalent) | 28.6% |
| state-aware | n/a (no ARSB equivalent) | 71.4% |
| policy-constrained | n/a (no ARSB equivalent) | 71.4% |

The recovery rate is the same definition in both projects (task
completed after a fault, no duplicates), but the fault coverage
differs: ARSB measures it on 4 tool-error-recovery scenarios
(timeout, malformed, unavailable, duplicate), RACRS on 7 fault
classes plus partial failure, rollback, confirmation and
delegation. The baseline's drop from 50.0% to 7.1% is explained
by that coverage: in ARSB its only recovery was
duplicate-delivery, and in RACRS it also faces stale,
incomplete and contradictory observations — its own and
delegated — which it cannot detect. The comparison is a
definition check, not a ranking.

## Limitations

- **Simulated agents, not models.** Every result is about four
  hand-written decision policies. Nothing here measures any real
  language model; a model-backed adapter behind the same
  `AgentAdapter` interface would produce different numbers, and
  its run-to-run variability would be non-zero.
- **One scenario per fault class.** With 17 scenarios, each
  per-category rate is a single task repeated over 3 seeds — four
  tasks for delegation. The headline rates are stable, but the
  per-category table should be read as a worked example per fault
  class, not as a statistically powered estimate.
- **Clean abort cannot see a missing confirmation.** A run counts
  as a clean abort when the task failed with no duplicates or
  side effects and the final state is the initial state or the
  expected state. In delegate-malformed-01 and
  delegate-unavailable-01 the non-verifying strategies reach the
  expected final state without the delegated confirmation ever
  arriving, so they count as clean aborts (baseline clean-abort
  rate 23.5%, up from 15.4% before the delegation tasks) while
  the payment went out unverified. The difference is visible
  only in the traces and the final state, not in the headline
  rate.
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
5. Verify delegated results the same way as tool results: a
   sub-agent's report is an observation, not a fact. Check it
   against a postcondition before acting on it, and do not pay
   or order on a delegated value you have not re-read.
