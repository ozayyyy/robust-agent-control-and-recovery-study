---
name: robust-agent-control-and-recovery-study
description: Run the Robust Agent Control and Recovery Study (RACRS) to measure how a tool-using agent recovers when its tools fail, lie, or go missing — use when testing agent recovery, comparing retry/verification/approval strategies, running the study on your own model or tasks, or adding a recovery task.
---

# Robust Agent Control and Recovery Study (RACRS)

Study of how tool-using agents behave when their plans are
interrupted by unreliable tools, changing state, partial failures,
conflicting observations, unexpected side effects — or a delegated
sub-agent that returns a bad result or goes missing.

It compares four recovery strategies — **baseline** (never retries,
never verifies), **retry-only** (bounded retries, no verification),
**state-aware** (verifies each step's postcondition, uses
idempotency keys, aborts and compensates on failure) and
**policy-constrained** (state-aware plus tool-side enforcement, an
approval gate and an action budget) — on 17 multi-step tasks over a
simulated payment ledger, inventory, file store and key-value
store. Faults: timeout, malformed response, unavailable tool,
stale / incomplete / contradictory observation, duplicate delivery,
plus partial failure, rollback, confirmation and delegation tasks.

It builds on the AI Agent Security Evaluation Framework and the
Agent Reliability and Safety Benchmark and reuses their interfaces
exactly (scenario schema, `AgentAdapter` interface, permission
model, JSONL trace format), so results are directly comparable
across the three. It is standalone: it does not import either one.

## Install

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

Python 3.10+, standard library only for the package itself;
pytest as a dev dependency. No network calls anywhere — all tools
are simulated in-process and all agents are deterministic
simulated planners.

## Run the study

```bash
# List the tasks
.venv/bin/python -m racrs list

# Run the full study (17 tasks x 4 strategies x seeds 0,1,2, 204 runs)
.venv/bin/python -m racrs run

# One strategy, one seed, reports and traces written out
.venv/bin/python -m racrs run --config state-aware --seeds 0 \
    --out examples --traces examples/traces

# Reproduce the published evaluation exactly
.venv/bin/python scripts/evaluate.py
```

## Run it on your own model

The four built-in strategies are pretend agents with fixed rules.
To use your own model instead, set three things in your terminal
(the key stays in your terminal only — it is never written into a
file, a trace or a report):

```bash
export RACRS_API_BASE_URL="https://api.example.com/v1"
export RACRS_API_KEY="paste-your-key-here"
export RACRS_MODEL="your-model-name"
```

The address must point at a chat API that works like OpenAI's
(`POST {base_url}/chat/completions`). Then either use the CLI:

```bash
.venv/bin/python -m racrs run --agent api --config state-aware --seeds 0
```

or the dedicated runner, which writes a report JSON (default
`examples/real-model-report.json`) recording which model and
endpoint produced it:

```bash
.venv/bin/python scripts/run_real_models.py
```

The runner runs every strategy once (seed 0 only, to keep the run
small — pass `--seeds 0,1,2` for the full run). Without a base URL
and a model it stops and writes nothing. If the API is down, slow,
or answers with text the study cannot read, the run does not stop
and does not crash: that step is left empty, the failure is
written in the trace, and the run carries on. You can also pass
the settings on the command line instead of the environment:
`--api-base-url`, `--api-key`, `--model`. A flag wins over the
matching environment variable.

## Run it on your own tasks

1. Copy one of the files in `scenarios/` and give it a new name.
   Pick the file closest to your own job — a payment, an order, a
   write-then-check job, a delegated check.
2. Change the steps to match your job: what the agent should do,
   what should be true after each step (the postcondition), and
   how to undo a step (the compensation).
3. Pick the problem to cause: a timeout, a wrong answer, a tool
   that says it failed after it worked, the same payment arriving
   twice, or a delegated sub-agent returning a stale,
   contradictory or malformed result, or going missing. Write it
   in `fault_schedule`, on the step it should hit.
4. Write down the final state you expect (`expected_final_state`)
   before you run it. A recovery only counts if the job finished
   with no double actions, no side effects and the final state
   you wrote down.
5. Run it:

```bash
.venv/bin/python -m racrs run --config state-aware --seeds 0
```

Required fields are the shared schema (`id`, `version`,
`category`, `title`, `user_task`, `scope`, `setup`,
`legitimate_steps`, `expected` with `must_complete` /
`must_not_complete`). RACRS fields are all optional:
`fault_schedule` (action key → `{"fault", "fail_times",
"output"}`; faults: `timeout`, `malformed`, `unavailable`,
`duplicate`, `stale`, `incomplete`, `contradictory` — the last
three apply to read operations only — plus the multiplicative
fault `gain`, `{"fault": "gain", "factor": 2}`), `plan_steps` (`{"action",
"postcondition", "compensate"}` per step), `expected_final_state`,
`permitted_side_effects`, `observation_followups`,
`confirmation_threshold`, `action_budget`. New categories: add
the category name to `RACRS_CATEGORIES` in
`racrs/scenario.py`, add the task to
`scripts/generate_scenarios.py` (which generates `scenarios/`),
and add a test in `tests/test_delegation.py` or
`tests/test_runner.py` asserting what each strategy must do.

## How to read the output

- `examples/report.json` — the published results: one entry per
  run (scenario, strategy, seed, attempted/completed/denied
  actions, duplicates, recovery outcome, final state) plus
  aggregate metrics per strategy.
- `examples/report.md` — the same results as tables: headline
  metrics per strategy, task success by category, recovery and
  duplicates by fault class.
- `examples/traces/*.jsonl` — one JSONL trace per seed-0 run:
  every decision, tool call, policy check, approval and
  observation, in order.
- `docs/evaluation.md` — the findings, written up with the
  numbers, the comparison with the earlier benchmark, and the
  limitations.
- `docs/methodology.md` — the definitions: what counts as a
  recovery, a clean abort, a duplicate, a side effect.
- `docs/strategies.md` — each strategy's policy and which
  mechanisms it reuses from the two earlier projects.

Key numbers in the published results (17 tasks x 4 strategies x
seeds 0, 1, 2 — 204 runs): state-aware 76.5% task success /
71.4% recovery / 0 duplicates; policy-constrained 70.6% /
71.4% / 0; retry-only 41.2% / 28.6% / 0.35 duplicates per run;
baseline 23.5% / 7.1% / 0.29. On the four delegation tasks:
verifying strategies 75.0% task success, baseline 0.0%; no
strategy recovers when the delegated sub-agent is unavailable,
but the verifying strategies refund the payment they already
made while the others leave it paid.

Definitions, in short: a **recovery** means the task completed
after a fault fired, with no duplicate actions, no unintended
side effects and the expected final state. Completing the task
*with* a duplicate or a side effect is counted separately
("continued with side effects"), not as a recovery. A **clean
abort** means the task failed but with no duplicates or side
effects and the initial state restored (or the expected state
reached).

## Safety rules

- Use fake data and the sandboxed tools only. Never point the
  study at real files, real money, real stock or a live tool.
- Never put your API key in a file or in a scenario — keep it in
  your terminal, as in "Run it on your own model" above.
- The simulated agents are pretend agents with fixed rules. The
  results measure the four decision policies and the enforcement
  architecture, not any real model. A model-backed run produces
  different numbers, and its run-to-run variability is non-zero.
- The action budget is enforced but no shipped task reaches it;
  "continued with side effects" is defined but unpopulated in
  this dataset (every duplicate also breaks the final state).

## What it must never be used for

- Never use it against production data, real credentials, live
  tools or real money.
- Never present the simulated-agent numbers as measurements of
  a real model. Real-model numbers come only from
  `scripts/run_real_models.py` run with your own endpoint and
  key, and they are labelled as such in the report.
- Never use it to claim a system is safe because the study
  passed: one task per fault class is a worked example, not a
  statistically powered estimate, and faults here are scheduled
  at fixed points, not emergent.

## Tests

```bash
.venv/bin/python -m pytest -q
```

Permissions, tools (including every fault class and idempotency),
scenario validation, agent retry/idempotency/compensation rules,
runner end-to-end per fault class, delegation tasks, scoring,
reporting, CLI, model adapter, the real-model runner against a
local stub endpoint, and compatibility with the two earlier
projects (real scenario files load; traces parse with their
trace fields).
