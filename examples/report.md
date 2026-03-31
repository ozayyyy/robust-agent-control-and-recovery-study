# Robust Agent Control and Recovery Study — Results

Runs: 204 (seeds 0, 1, 2).
Agents are deterministic simulated decision policies, not language models; results measure the agent policies and the enforcement architecture, not any real model's behaviour. Scoring is rule-based; no LLM judge is used. Recovery means the task completed after a fault fired, with no duplicate actions, no unintended side effects and the expected final state — completing the task with a duplicate or a side effect is counted separately, not as a recovery.

## Headline metrics

| Configuration | Task success | Recovery success | Continued with side effects | Clean abort | Duplicates / run | Unintended / run | Mean tool calls | Mean retries | Mean approvals denied | State match | Run-to-run consistency |
|---|---|---|---|---|---|---|---|---|---|---|---|
| baseline | 23.5% | 7.1% | 0.0% | 23.5% | 0.29 | 0.00 | 2.8 | 0.00 | 0.00 | 35.3% | 100.0% |
| policy-constrained | 70.6% | 71.4% | 0.0% | 29.4% | 0.00 | 0.00 | 3.8 | 0.59 | 0.06 | 70.6% | 100.0% |
| retry-only | 41.2% | 28.6% | 0.0% | 5.9% | 0.35 | 0.00 | 3.1 | 0.35 | 0.00 | 47.1% | 100.0% |
| state-aware | 76.5% | 71.4% | 0.0% | 23.5% | 0.00 | 0.00 | 3.9 | 0.59 | 0.00 | 76.5% | 100.0% |

## Task success by category

| Category | baseline | policy-constrained | retry-only | state-aware |
|---|---|---|---|---|
| benign | 100.0% | 100.0% | 100.0% | 100.0% |
| confirmation | 100.0% | 50.0% | 100.0% | 100.0% |
| contradictory-observation | 0.0% | 100.0% | 0.0% | 100.0% |
| delegation | 0.0% | 75.0% | 25.0% | 75.0% |
| duplicate-delivery | 100.0% | 100.0% | 0.0% | 100.0% |
| incomplete-observation | 0.0% | 100.0% | 0.0% | 100.0% |
| malformed | 0.0% | 100.0% | 100.0% | 100.0% |
| multi-fault | 0.0% | 100.0% | 100.0% | 100.0% |
| partial-failure | 0.0% | 0.0% | 0.0% | 0.0% |
| rollback | 0.0% | 0.0% | 0.0% | 0.0% |
| stale-observation | 0.0% | 100.0% | 0.0% | 100.0% |
| timeout | 0.0% | 100.0% | 100.0% | 100.0% |
| unavailable | 0.0% | 0.0% | 0.0% | 0.0% |

## Recovery success by fault class

| Fault | baseline | policy-constrained | retry-only | state-aware |
|---|---|---|---|---|
| contradictory | 0.0% | 100.0% | 0.0% | 100.0% |
| duplicate | 100.0% | 100.0% | 0.0% | 100.0% |
| incomplete | 0.0% | 100.0% | 0.0% | 100.0% |
| malformed | 0.0% | 100.0% | 100.0% | 100.0% |
| stale | 0.0% | 100.0% | 0.0% | 100.0% |
| timeout | 0.0% | 100.0% | 100.0% | 100.0% |
| unavailable | 0.0% | 0.0% | 0.0% | 0.0% |

## Duplicates per run by fault class

| Fault | baseline | policy-constrained | retry-only | state-aware |
|---|---|---|---|---|
| contradictory | 1.00 | 0.00 | 1.00 | 0.00 |
| duplicate | 0.00 | 0.00 | 1.00 | 0.00 |
| incomplete | 1.00 | 0.00 | 1.00 | 0.00 |
| malformed | 0.00 | 0.00 | 0.00 | 0.00 |
| stale | 1.00 | 0.00 | 1.00 | 0.00 |
| timeout | 0.00 | 0.00 | 0.00 | 0.00 |
| unavailable | 0.00 | 0.00 | 0.00 | 0.00 |

## Comparison with ARSB (published results)

ARSB's headline numbers (37 scenarios v1.0 x 4 configs, seeds 0, 1, 2, 444 runs) are reference data, not measured here. ARSB's recovery rate is measured on its 4 tool-error-recovery scenarios only (timeout, malformed, unavailable, duplicate); RACRS measures the same quantity over 7 fault classes plus partial failure, rollback and confirmation, so the two recovery rates are the same definition on different fault coverage — the comparison is a definition check, not a ranking.

| Configuration | ARSB recovery | RACRS recovery success |
|---|---|---|
| baseline | 50.0% | 7.1% |
| retry-only | n/a (no ARSB equivalent) | 28.6% |
| state-aware | n/a (no ARSB equivalent) | 71.4% |
| policy-constrained | n/a (no ARSB equivalent) | 71.4% |

## Reading the results

- Baseline never retries and never verifies: it survives a one-off fault only when the fault does not matter to the outcome, and it follows a stale or contradictory observation into a duplicate action.
- Retry-only fixes timeouts and malformed responses, but it retries an error reported after an action already completed, so it is the only strategy that duplicates a delivery — retrying without verifying is worse than not retrying, for that fault class.
- State-aware verifies each step's postcondition before accepting it and uses idempotency keys, so it recovers from transient faults without duplicating, and it aborts and compensates instead of leaving the system in a half-finished state.
- Policy-constrained adds tool-side enforcement, the approval gate and an action budget to the state-aware policy. It pays for that with the confirmation scenario: a large payment without pre-approval is blocked, so the task fails cleanly instead of completing. That is the control / usefulness trade-off, measured.
- Run-to-run consistency is 100% for every strategy: the policies are deterministic and the fault schedule is fixed per scenario, so repeated seeds reproduce the same runs. Variability in this study is across fault classes and strategies, not across seeds.
