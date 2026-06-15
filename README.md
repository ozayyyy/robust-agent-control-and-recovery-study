# Robust Agent Control and Recovery Study (RACRS)

Study of how tool-using AI agents behave when their plans are
interrupted by unreliable tools, changing state, partial failures,
conflicting observations or unexpected side effects.

It builds on two earlier projects and reuses their interfaces
exactly, so all three projects' results are directly comparable:

- **Project 7, AI Agent Security Evaluation Framework (AASEF):**
  the scenario schema, the `AgentAdapter` interface, the
  permission model (scope, boundary check, approval gate) and the
  JSONL trace format.
- **Project 8, Agent Reliability and Safety Benchmark (ARSB):**
  the same interfaces plus bounded retries, verify-before-retry,
  refusal handling and the recovery metric.

RACRS is standalone: it does not import `aasef` or `arsb`. It
mirrors their interfaces module by module and extends them in
backwards-compatible ways only — a 7 scenario file and an 8
scenario file both load here unchanged (tested in
`tests/test_compat.py`, including all 34 real 7 scenario files
and all 37 real 8 scenario files). The mapping, and what is new
in RACRS, is in `docs/architecture.md`.

## What it measures

Four recovery strategies — **baseline**, **retry-only**,
**state-aware**, **policy-constrained** — on 13 multi-step tasks
over a simulated payment ledger, inventory, file store and
key-value store, with 7 fault classes injected at reproducible
points: timeout, malformed response, unavailable tool, stale
observation, incomplete observation, contradictory observation
and duplicate delivery, plus partial failure, rollback and
confirmation tasks.

Recovery is defined strictly: the task completed after a fault
fired, with no duplicate actions, no unintended side effects and
the expected final state. Completing the task *with* a duplicate
or a side effect is counted separately ("continued with side
effects"), not as a recovery. See `docs/methodology.md` for the
definitions and `docs/strategies.md` for each strategy's policy
and which 7/8 mechanisms it reuses.

## Measured results

13 scenarios x 4 configurations x seeds 0, 1, 2 — 156 runs.
Full results in `examples/report.md`, `docs/evaluation.md`.

| Configuration | Task success | Recovery success | Duplicates / run | Clean abort | Mean tool calls |
|---|---|---|---|---|---|
| baseline | 30.8% | 10.0% | 0.23 | 15.4% | 2.7 |
| retry-only | 46.2% | 30.0% | 0.31 | 0.0% | 3.1 |
| state-aware | 76.9% | 70.0% | 0.00 | 23.1% | 3.8 |
| policy-constrained | 69.2% | 70.0% | 0.00 | 30.8% | 3.7 |

Headline findings: retrying without verifying is worse than not
retrying for duplicate delivery (retry-only is the only strategy
that duplicates a payment); verification, not retrying, is what
fixes stale, incomplete and contradictory observations; no
strategy recovers from an unavailable tool, but the verifying
strategies abort cleanly instead of leaving a half-finished
state; the policy-constrained configuration pays for its approval
gate with one blocked task (a large payment without
pre-approval).

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

Python 3.10+, standard library only for the package itself;
pytest as a dev dependency. No network calls, no real LLM or API
calls anywhere — all tools are simulated in-process and all agents
are deterministic simulated planners.

## How to run

```bash
# List the scenarios
.venv/bin/python -m racrs list

# Run the full study (13 scenarios x 4 configs x seeds 0,1,2)
.venv/bin/python -m racrs run

# One configuration, one seed, reports and traces written out
.venv/bin/python -m racrs run --config state-aware --seeds 0 \
    --out examples --traces examples/traces

# Reproduce the published evaluation exactly
.venv/bin/python scripts/evaluate.py
```

## How to add a task

Add one JSON file to `scenarios/` (or edit
`scripts/generate_scenarios.py`, which generates them). Required
fields are the 7/8 schema (`id`, `version`, `category`, `title`,
`user_task`, `scope`, `setup`, `legitimate_steps`, `expected`
with `must_complete` / `must_not_complete`). RACRS fields are
all optional:

- `fault_schedule`: action key → `{"fault", "fail_times",
  "output"}`. Faults: `timeout`, `malformed`, `unavailable`,
  `duplicate`, `stale`, `incomplete`, `contradictory`
  (observation faults apply to read operations only).
- `plan_steps`: `{"action", "postcondition", "compensate"}` per
  step. `postcondition` is `{"tool", "op", "target",
  "expected_contains"}`; `compensate` lists the actions that undo
  the step.
- `expected_final_state`: partial `{"files", "kv", "ledger",
  "inventory", "orders"}` mapping — only the keys present are
  compared.
- `observation_followups`: `[{"if_observation_contains": str,
  "actions": [...]}]` — what an agent that takes an observation
  at face value does next.
- `confirmation_threshold`, `action_budget`: see
  `docs/architecture.md`.

## How to add a fault

Add an entry to the scenario's `fault_schedule` for the action
key it should hit, and a corresponding fault class in
`racrs/tools.py` if it is a new kind of failure (follow the
existing `timeout` / `stale` implementations: a fault either
fails the call, or completes it with a wrong observation and a
`fault` field on the result). Faults fire per action key with a
fixed `fail_times`, so runs are reproducible across seeds.

## How recovery is scored

See `docs/methodology.md`. In short: a fault fired, the task
completed (all `must_complete` actions **and** the expected
final state), no duplicates, no unintended side effects. A run
that completes with a duplicate is "continued with side
effects"; a failed run with no duplicates or side effects and
the initial state restored is a "clean abort".

## Tests

```bash
.venv/bin/python -m pytest -q
```

74 tests: permissions, tools (including every fault class and
idempotency), scenario validation, agent retry/idempotency/
compensation rules, runner end-to-end per fault class, scoring
(including the recovery vs continued distinction), reporting,
CLI, and 7/8 compatibility (real 7 and 8 scenario files load;
RACRS traces parse with 7/8's trace fields).

## Limitations

- Simulated agents, not models: results are about four
  hand-written decision policies. A model-backed adapter behind
  the same `AgentAdapter` interface would produce different
  numbers.
- One scenario per fault class (13 scenarios total): per-category
  rates are a worked example per fault class, not a statistically
  powered estimate.
- Faults are scheduled at fixed points, not emergent; compensations
  are pre-written in the scenario, not derived by the agent.
- The action budget is enforced and unit-tested but never reached
  by any scenario; "continued with side effects" is defined but
  unpopulated in this dataset (every duplicate also breaks the
  final state).

Full limitations and recommendations: `docs/evaluation.md`.
