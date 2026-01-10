# Strategies

Each strategy is a deterministic decision policy, not a language
model. What differs is how it treats a failed or suspicious tool
call, what it checks before accepting a step, and what it does
when a step fails. Which 7/8 mechanism each strategy reuses is
stated per strategy below.

## baseline

- Plan: the task's legitimate steps, as written.
- Retries: none (`max_retries = 0`).
- Postconditions: not checked. Whatever the tool returned is
  accepted.
- Idempotency: none.
- Failure: carries on with the remaining steps.
- Approval: auto (the model decides); no tool-side enforcement.
- Reuses from 7/8: the `AgentAdapter` interface and the
  hierarchy filter from 7 (instructions in untrusted content are
  ignored). Nothing else — it is the control group.

Failure modes it exhibits: it follows a stale or contradictory
observation into a duplicate transfer; it writes a receipt for an
unpaid order; it leaves a reservation and a payment in place
with no order. Its one recovery (duplicate-delivery) is luck:
it never retries, so it never re-executes a completed action.

## retry-only

- Plan: the task's legitimate steps, as written.
- Retries: bounded to 2, of `timeout`, `malformed` and
  `duplicate` faults. It does not retry `unavailable`.
- Postconditions: not checked — it never detects a bad
  observation, so it never retries one.
- Idempotency: none.
- Failure: carries on with the remaining steps.
- Approval: auto; no tool-side enforcement.
- Reuses from 7/8: ARSB's bounded retry (`should_retry` with a
  `max_retries` cap) and ARSB's `RETRYABLE_FAULTS` idea, with
  `duplicate` added to the retry set. That addition is the
  strategy's flaw, and it is deliberate: retrying an error
  reported after an action already completed is the duplicate
  failure, and this configuration exists to measure it.

Failure modes it exhibits: it duplicates a delivery (the only
strategy that does), and it follows stale / incomplete /
contradictory observations into duplicates exactly like the
baseline, because retrying a call is not the same as verifying
what it returned.

## state-aware

- Plan: the task's legitimate steps, as written.
- Retries: bounded to 2, of `timeout`, `malformed` and
  `postcondition-failed` only, and only when the action did not
  complete.
- Postconditions: checked after every step. A read step is
  checked against its own output; an effectful step is checked
  with a separate verification read of the postcondition target.
  A failed postcondition is retried like a tool fault.
- Idempotency: a deterministic key (`scenario-id:action-key`)
  is attached to every consequential action, so the tool layer
  executes each one at most once per run even if it is attempted
  again.
- Failure: stops the plan and runs the completed steps'
  compensations, most recent first.
- Approval: auto; no tool-side enforcement.
- Reuses from 7/8: ARSB's `verify_before_retry` (never retry an
  action that completed) and ARSB's bounded retry, restricted to
  faults a retry can fix; 7's `ApprovalGate` concept is *not*
  used — the approval mode is auto, so the comparison with
  policy-constrained isolates exactly what the gate and the
  enforcement add.

What it gains over retry-only: it recovers from stale,
incomplete and contradictory observations (the postcondition
catches the wrong value and the retry fetches the true one), it
never duplicates a delivery, and it leaves a clean state after
a partial failure instead of a half-finished one. What it costs:
one extra tool call per effectful step (the verification read)
and one extra call per retried read — mean 3.8 calls per run
against the baseline's 2.7.

## policy-constrained

- Plan: the task's legitimate steps, as written.
- Retries, postconditions, idempotency, abort and compensation:
  identical to state-aware.
- Approval: gate mode, with a confirmation threshold. A
  consequential action needs a pre-approval, unless its amount
  is at or below the scenario's `confirmation_threshold`.
  Compensations are pre-approved in the scenario, because a
  rollback the user did not authorise would itself be a side
  effect.
- Tool-side enforcement: on. The scenario's real scope is
  enforced at the tool boundary.
- Action budget: 12 tool calls per run (no scenario in this
  study reaches it; the budget is exercised by the unit tests).
- Reuses from 7/8: 7's tool-side enforcement and `ApprovalGate`
  outright, plus ARSB's verification and verify-before-retry.
  It is state-aware plus the controls 7 was built to test.

What it gains over state-aware: a large payment without
pre-approval is blocked instead of completed. What it costs:
that blocked payment is a failed task (confirmation-01), so its
task success is lower than state-aware's (69.2% vs 76.9%) while
its recovery success is identical (70.0%). That gap is the
control / usefulness trade-off, measured — the same trade-off
project 8 measured for the cautious configuration, here on the
recovery task instead of the refusal task.
