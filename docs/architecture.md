# Architecture

## Module map

```
racrs/
  scenario.py       Scenario schema: 7/8's schema, plus RACRS extensions.
  permissions.py    Scope, Action, boundary check, approval gate (as 7/8).
  tools.py          Sandboxed tools over an in-memory Sandbox + faults.
  agents.py         AgentAdapter interface + four recovery strategies.
  runner.py         Repeatable execution: one scenario x one config x one seed.
  scoring.py        Metrics aggregation, including recovery and clean abort.
  reporting.py      JSON + Markdown reports, with an ARSB comparison table.
  trace.py          Ordered event log (JSONL), 7/8 format.
  arsb_reference.py ARSB's published headline numbers (reference data).
  cli.py            `racrs list` / `racrs run`.
  model_adapter.py  Model-backed agent: your own model over an
                    OpenAI-compatible chat API (`--agent api`).
```

Rules: `permissions.py` and `tools.py` never import the agent or the
runner. The boundary check depends only on the action and the scope,
so it can be reused without the rest of the framework. The runner
depends on agents, tools and traces; scoring and reporting depend
only on run results.

## Model-backed agents (`racrs/model_adapter.py`)

`ApiModelAdapter` implements the same `AgentAdapter` interface as
the simulated agents, so a model-backed run goes through the same
runner, tools, boundary, gate and scoring. The model only supplies
the plan: it is asked (OpenAI-compatible `POST
{base_url}/chat/completions`, stdlib `urllib` only) with a system
message listing the allowed tools and the scope, and a user message
with the task, the plan steps and postconditions, and the
observations so far. It must reply with a JSON array of actions;
surrounding text and markdown fences are tolerated, and entries
with an unknown tool, unknown op, non-string target or non-object
args are dropped. `should_refuse`, `should_retry`,
`compensation_for` and `idempotency_key` are the same rules as
`SimulatedAgent` for the configuration in use, so a model run with
the state-aware configuration verifies postconditions and uses
idempotency keys exactly as the simulated one does.

Settings resolve in this order: CLI flag, environment variable,
nothing. `RACRS_API_BASE_URL` has no default and `RACRS_MODEL`
has no built-in name; a missing one raises `ApiSettingsError`
with a message naming the setting. The key (`RACRS_API_KEY` or
`--api-key`) is sent in one HTTP header and never written to a
trace, a report, a log or stdout. A failed call (HTTP error,
timeout of 30 seconds, unparseable reply) returns an empty plan,
records the failure in `last_error` — which the runner writes to
the trace — and never retries the network call.

## Mapping to projects 7 and 8

RACRS is a standalone repo: it does not import `aasef` or `arsb`.
It mirrors their interfaces exactly, module by module, so results
from the three projects are directly comparable.

| RACRS module | 7 / 8 module | Relationship |
|---|---|---|
| `racrs/scenario.py` | `aasef/scenario.py`, `arsb/scenario.py` | Same schema and validation. Adds optional fields only (below). |
| `racrs/permissions.py` | `aasef/permissions.py`, `arsb/permissions.py` | Identical `Action`, `Scope`, `PolicyDecision`, `check_boundary` rule order, `ApprovalGate`. Adds ledger / inventory tools and a confirmation threshold (below). |
| `racrs/tools.py` | `aasef/tools.py`, `arsb/tools.py` | Same `Sandbox`, `ToolSet`, shell allowlist, ARSB fault shape. Adds ledger / inventory tools, observation faults, idempotency (below). |
| `racrs/agents.py` | `aasef/agents.py`, `arsb/agents.py` | Same `AgentAdapter` interface (`plan_legitimate`, `plan_after_observation`, `should_refuse`, `should_retry`) and the same seeded choice between readings. Adds two methods and four new configurations (below). |
| `racrs/runner.py` | `aasef/runner.py`, `arsb/runner.py` | Same execution flow and the same permissive-scope rule for non-enforced configs. Adds postconditions, abort / compensation, budget, final-state check (below). |
| `racrs/scoring.py` | `aasef/scoring.py`, `arsb/scoring.py` | Same rate definitions for the shared metrics (`task_success_rate`, `recovery_rate`, `run_to_run_consistency`). Adds recovery-success, clean-abort, duplicate / side-effect and overhead metrics. |
| `racrs/reporting.py` | `aasef/reporting.py`, `arsb/reporting.py` | Same JSON + Markdown shape. Adds the ARSB comparison table. |
| `racrs/trace.py` | `aasef/trace.py`, `arsb/trace.py` | Identical JSONL format (see below). |
| `racrs/cli.py` | `aasef/cli.py`, `arsb/cli.py` | Same `list` / `run` commands, plus `--seeds`. |

## Backwards-compatible extensions

Nothing below changes the meaning of any 7/8 field. A 7 scenario
file and an 8 scenario file both load in RACRS unchanged (tested in
`tests/test_compat.py`, including all 34 real 7 scenario files and
all 37 real 8 scenario files), and a RACRS trace parses with 7/8's
trace fields.

### Scenario schema (`racrs/scenario.py`)

7 categories and 8's seven categories are accepted unchanged.
RACRS adds twelve categories: `timeout`, `malformed`,
`unavailable`, `stale-observation`, `incomplete-observation`,
`contradictory-observation`, `duplicate-delivery`,
`partial-failure`, `rollback`, `confirmation`, `multi-fault`,
`delegation`.

Optional fields, all defaulting to "absent":

- `fault_schedule`: the fault schedule for this task, mapping
  action key to `{"fault", "fail_times", "output"}`. The same shape
  as ARSB's `tool_faults`; if both are present, `fault_schedule`
  wins. Faults: ARSB's `timeout`, `malformed`, `unavailable`,
  `duplicate`, plus RACRS's observation faults `stale`,
  `incomplete`, `contradictory` (read operations only, validated
  on load).
- `plan_steps`: the task's multi-step plan, a list of
  `{"action", "postcondition", "compensate"}`. `postcondition` is
  `{"tool", "op", "target", "expected_contains"}`. `compensate`
  is a list of actions that undo the step. When absent, the plan
  is the `legitimate_steps` with no postconditions and no
  compensations.
- `expected_final_state`: the sandbox state a correct run ends in,
  as a partial `{"files", "kv", "ledger", "inventory", "orders"}`
  mapping. Only the keys present are compared; `orders` is the
  expected number of orders.
- `permitted_side_effects`: action keys that may complete in
  addition to `must_complete`.
- `observation_followups`: `[{"if_observation_contains": str,
  "actions": [...]}]`. An agent that takes an observation at face
  value follows the matching rule.
- `confirmation_threshold`: amounts at or below this value are
  approved even in gate mode. Default 0: the 7/8 behaviour.
- `action_budget`: maximum tool calls for the run. Default 0: no
  budget (the policy-constrained configuration's own default of
  12 then applies).

### Permission model (`racrs/permissions.py`)

- `TOOL_OPS` gains `ledger: {transfer, balance}` and
  `inventory: {reserve, release, order, get}` — the simulated
  payment ledger and stock/order store.
- `Scope` gains `allowed_accounts` and `allowed_items`, both
  defaulting to the accounts / items the study uses.
  `Scope.from_dict` supplies the defaults when a 7/8-format
  scenario has no such fields.
- `check_boundary` gains ledger / inventory target rules, checked
  in the same position as the file / web / kv target rules.
- `CONSEQUENTIAL_OPS` gains `transfer`, `reserve`, `order`:
  they move money or stock, so they need an approval decision
  when gates are on, exactly like `write` / `send` / `spend` in
  7/8.
- `ApprovalGate` gains an optional `confirmation_threshold` (see
  the module docstring). The default (`None`) is the 7/8
  behaviour.

### Tools (`racrs/tools.py`)

- `Sandbox` gains `ledger` (account → balance), `inventory`
  (item → stock), `orders` and `reservations`, plus
  `snapshot()` / `initial_snapshot()` for state comparison, and
  the setup-time values used by the stale fault.
- `ToolSet` gains three observation faults: `stale` (the read
  returns the value the target held at setup time, or the fault
  spec's explicit `output`), `incomplete` (the read returns the
  first half of the true output plus an `[INCOMPLETE]` marker)
  and `contradictory` (the read returns the spec's explicit
  `output`, or a `CONTRADICTORY:`-prefixed value). Like ARSB's
  `duplicate` fault, an observation fault completes the call
  (`ok=True`) with a wrong output and a `fault` field — the call
  succeeded, the observation is wrong.
- `ToolSet.call` gains a `faults` flag (default `True`). The
  runner calls verification reads with `faults=False`, so a
  scheduled fault lands on the plan step it is defined for — the
  observation the agent acts on — not on the agent's internal
  check of that step. Without this, a fault attached to a balance
  read would be consumed by the transfer step's verification read
  and the plan step would never see it; the fault would also go
  unrecorded, and the run would be misclassified as "no-fault".
  This was found during development (the state-aware stale /
  contradictory runs initially recorded no fault) and fixed
  before the evaluation was run.
- Idempotency: an action whose `args` carry an
  `idempotency_key` is executed at most once per run. A repeat
  call with the same key returns the stored result with
  `fault="idempotent-replay"` and does not touch state again.

### Agent adapter (`racrs/agents.py`)

- `AgentConfig` gains `verify_postconditions` (default `False`),
  `use_idempotency` (default `False`), `action_budget` (default
  `0`, unlimited), `abort_on_failure` (default `False`) and
  `rollback_on_failure` (default `False`). The 7/8 fields keep
  their meanings.
- `AgentAdapter.compensation_for(action, scenario)` and
  `AgentAdapter.idempotency_key(action, scenario)`: new methods
  the runner consults. The defaults return no compensation and
  no key, which is exactly the 7/8 behaviour.
- The four configurations are `baseline`, `retry-only`,
  `state-aware` and `policy-constrained` (see
  `docs/strategies.md`).

### Runner (`racrs/runner.py`)

- Postcondition checks: a read step is checked against its own
  output; an effectful step is checked with a separate
  verification read of the postcondition target. A failed
  postcondition is a retryable failure (`postcondition-failed`)
  for the verifying strategies, and is invisible to the others.
  Only the *accepted* observation — the one that passed the
  check, after any retry — is handed to the agent for follow-up
  decisions. The rejected faulty observation stays in the trace,
  never in the agent's decision input.
- Abort and compensation: when a step fails and the configuration
  aborts on failure, the plan stops and the completed steps'
  compensations run in reverse order. Compensations are part of
  the task (they are pre-approved in the scenario, because a
  rollback the user did not authorise would itself be a side
  effect).
- Action budget: every tool call, including verification reads,
  counts against the run's budget; exceeding it stops the run.
- Final-state check: the sandbox state at the end of the run is
  compared with `expected_final_state` and with the initial
  state. `task_completed` requires the expected final state, not
  just the `must_complete` actions.
- `RunResult` gains `state_matches`, `clean_abort`,
  `unintended_side_effects`, `tool_calls`, `retries`,
  `approvals_requested`, `approvals_denied`, `compensations`,
  `budget_exceeded`, `faults_fired`, `final_state` and
  `recovery_outcome`. The 7/8 fields keep their meanings, with
  one clarification carried over from ARSB: `task_completed` is
  False when a scenario has no `must_complete` actions.

## Execution flow

1. Load scenarios, build one `Sandbox` per run from `setup`.
2. If the agent refuses the task, record the refusal and stop.
3. Agent plans legitimate steps; the runner executes each through
   the approval gate (consequential ops) and then the tool boundary.
   A tool fault may cause a bounded retry, decided by the agent.
   A failed postcondition may cause a retry of the step.
4. If a step fails and the configuration aborts on failure, stop
   the plan and run the completed steps' compensations.
5. Otherwise, observations are collected; the agent plans
   follow-up steps from what it observed (accepted observations
   only), and those are executed too.
6. The result records attempted vs completed actions separately,
   `attack_success`, `task_completed`, `false_refusal`, `refused`,
   `duplicates`, `recovered`, `state_matches`, `clean_abort` and
   the recovery outcome.
7. Scoring aggregates per configuration, per category and per
   fault class over all seeds; reporting writes JSON and Markdown,
   including the ARSB comparison table.

## Trace format

Identical to 7/8: JSONL, one header line
(`{"trace": {scenario_id, config, seed}}`) followed by one event
per line: `{seq, kind, actor, summary, detail}`. Kinds: `decision`,
`tool_call`, `policy`, `approval`, `observation`, `result`. A
refusal is a `decision` event with `detail.refused = True`, a retry
is a `decision` event, a verification read is a `tool_call` event
with `detail.verification = True`, a compensation is a `decision`
event with `detail.compensation = True` followed by ordinary
`tool_call` events, and the final `result` event carries the RACRS
outcome fields inside `detail` — no new kinds, so a 7/8 trace
parser reads RACRS traces unchanged.
