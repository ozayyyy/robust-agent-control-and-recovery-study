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
**state-aware**, **policy-constrained** — on 17 multi-step tasks
over a simulated payment ledger, inventory, file store and
key-value store, with 7 fault classes injected at reproducible
points: timeout, malformed response, unavailable tool, stale
observation, incomplete observation, contradictory observation
and duplicate delivery, plus partial failure, rollback,
confirmation, and four delegation tasks, where a delegated
sub-agent returns a stale, contradictory or malformed result,
or is unavailable.

Recovery is defined strictly: the task completed after a fault
fired, with no duplicate actions, no unintended side effects and
the expected final state. Completing the task *with* a duplicate
or a side effect is counted separately ("continued with side
effects"), not as a recovery. See `docs/methodology.md` for the
definitions and `docs/strategies.md` for each strategy's policy
and which 7/8 mechanisms it reuses.

## Measured results

17 scenarios x 4 configurations x seeds 0, 1, 2 — 204 runs.
Full results in `examples/report.md`, `docs/evaluation.md`.

| Configuration | Task success | Recovery success | Duplicates / run | Clean abort | Mean tool calls |
|---|---|---|---|---|---|
| baseline | 23.5% | 7.1% | 0.29 | 23.5% | 2.8 |
| retry-only | 41.2% | 28.6% | 0.35 | 5.9% | 3.1 |
| state-aware | 76.5% | 71.4% | 0.00 | 23.5% | 3.9 |
| policy-constrained | 70.6% | 71.4% | 0.00 | 29.4% | 3.8 |

Headline findings: retrying without verifying is worse than not
retrying for duplicate delivery (retry-only is the only strategy
that duplicates a payment); verification, not retrying, is what
fixes stale, incomplete and contradictory observations — its own
and delegated (the verifying strategies score 75.0% task success
on the four delegation tasks, the baseline 0.0%); no strategy
recovers from an unavailable tool, but the verifying strategies
abort cleanly instead of leaving a half-finished state — when
the delegated sub-agent is down they refund the payment they
already made, while the others leave it paid and write a receipt
for a payment nobody confirmed; the policy-constrained
configuration pays for its approval gate with one blocked task
(a large payment without pre-approval).

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

# Run the full study (17 scenarios x 4 configs x seeds 0,1,2)
.venv/bin/python -m racrs run

# One configuration, one seed, reports and traces written out
.venv/bin/python -m racrs run --config state-aware --seeds 0 \
    --out examples --traces examples/traces

# Reproduce the published evaluation exactly
.venv/bin/python scripts/evaluate.py
```

## Using it on your own model

The four built-in strategies are pretend agents with fixed rules.
This section is for using your own model instead.

1. Set three things in your terminal. The first is where your
   model lives. The second is your key. The third is which model
   to use:
   ```bash
   export RACRS_API_BASE_URL="https://api.example.com/v1"
   export RACRS_API_KEY="paste-your-key-here"
   export RACRS_MODEL="your-model-name"
   ```
   The address must point at a chat API that works like OpenAI's
   (`POST {base_url}/chat/completions`). The key stays in your
   terminal only: it is never written into a file, a trace or a
   report.
2. Run the study with your model:
   ```bash
   .venv/bin/python -m racrs run --agent api --config state-aware --seeds 0
   ```
   The model plans the steps. Everything else works the same way:
   the sandboxed tools, the permission checks, the approval gate,
   the postconditions and the scoring. A model answer can never do
   more than the scope and the gate allow.
3. If the API is down, slow, or answers with text the study cannot
   read, the run does not stop and does not crash. That step is
   left empty, the failure is written in the trace, and the run
   carries on. You can also pass the settings on the command line
   instead of the environment: `--api-base-url`, `--api-key`,
   `--model`. A flag wins over the matching environment variable.

## Running it with a real model

`scripts/run_real_models.py` runs the same study with your model
as the planner and writes a report JSON (default
`examples/real-model-report.json`):

```bash
export RACRS_API_BASE_URL="https://api.example.com/v1"
export RACRS_API_KEY="paste-your-key-here"
export RACRS_MODEL="your-model-name"
.venv/bin/python scripts/run_real_models.py
```

It runs every configuration once (seed 0 only, to keep the run
small — pass `--seeds 0,1,2` for the full run). The report records
which model and endpoint produced it, and a note that the numbers
are real-model numbers, not the simulated ones in
`examples/report.json`. The key is never written to the report.
Without a base URL and a model the script stops and writes
nothing — there are no real-model numbers in this repo until you
run it with your own endpoint and key. The runner is validated
against a local stub endpoint in
`tests/test_real_model_runner.py`.

## Using it on your own tasks

1. Copy one of the files in `scenarios/` and give it a new name.
   Pick the file closest to your own job — a payment, an order,
   a write-then-check job.
2. Change the steps to match your job: what the agent should do,
   what should be true after each step (the postcondition), and
   how to undo a step (the compensation).
3. Pick the problem to cause: a timeout, a wrong answer, a tool
   that says it failed after it worked, or the same payment
   arriving twice. Write it in `fault_schedule`, on the step it
   should hit.
4. Write down the final state you expect (`expected_final_state`)
   before you run it. A recovery only counts if the job finished
   with no double actions, no side effects and the final state
   you wrote down.
5. Run it:
   ```bash
   .venv/bin/python -m racrs run --config state-aware --seeds 0
   ```

Safety rules for both sections above: use fake data and the
sandboxed tools only. Never point the study at real files, real
money, real stock or a live tool. Never put your API key in a file
or in a scenario — keep it in your terminal, as in step 1 of
"Using it on your own model".

## Using it with an AI agent

`SKILL.md` at the project root is a skill file for AI agents: it
says what the study does, how to install and run it, how to read
the reports, and what it must never be used for. If your agent
supports skills, point it at this project and ask it to use the
skill — for example, to run the study, to run it on your own
model, or to add a task of your own.

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
  (observation faults apply to read operations only), plus the
  multiplicative fault `gain` (`{"fault": "gain", "factor": 2}` —
  a scaled quantity; see `docs/counterfactual.md`).
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

## Counterfactual module

`racrs/counterfactual.py` asks the paper's question about
recovery: what would have happened under a different strategy
in the same event, with the same fault? It replays each task
with the same fault schedule under all four strategies (paired
re-runs), compares persistent faults (identical every time)
with fresh ones (new severity per seed), counts where a
strategy's correction helps vs hurts against the no-retry
baseline, and replans failed runs under different policies to
see whether the goal was reachable at all. It also adds the
`gain` fault class — a multiplied quantity, the paper's
offset-vs-gain distinction. Headline: fresh faults cut
recovery from 71.4% to 40.5% for the verifying strategies (a
severity of 3 defeats a retry budget of 2); state-aware helps
41 times and hurts never; 71 of 219 failed runs reached the
goal under some other strategy, 148 under none. Full results
and limits: `docs/counterfactual.md`.

Inspiration: "Counterfactual World Models: JEPAs That Reason
About 'What If'" by Randall Balestriero and Yann LeCun
(arXiv:2611.24778, https://arxiv.org/abs/2611.24778; code at
https://github.com/galilai-group/counterfactual-WM). The
implementation here is original paired re-runs written for
this study — it does not use the paper's code or its
residual-reuse formula.

## Tests

```bash
.venv/bin/python -m pytest -q
```

134 tests: permissions, tools (including every fault class and
idempotency), scenario validation, agent retry/idempotency/
compensation rules, runner end-to-end per fault class, delegation
tasks, scoring (including the recovery vs continued distinction),
counterfactual recovery (paired re-runs, persistent vs fresh
faults, helps vs hurts, hindsight replanning, the gain fault
class), reporting, CLI, model adapter, the real-model runner against a
local stub endpoint, and 7/8 compatibility (real 7 and 8 scenario
files load; RACRS traces parse with 7/8's trace fields).

## Limitations

- Simulated agents, not models: results are about four
  hand-written decision policies. A model-backed adapter behind
  the same `AgentAdapter` interface would produce different
  numbers.
- One scenario per fault class (17 scenarios total): per-category
  rates are a worked example per fault class, not a statistically
  powered estimate. The delegation category has four tasks.
- Clean abort cannot see a missing confirmation: in two
  delegation tasks the non-verifying strategies reach the
  expected final state without the delegated confirmation ever
  arriving, so they count as clean aborts while the payment went
  out unverified. The difference is visible only in the traces
  and the final state, not in the headline rate. See
  `docs/evaluation.md`.
- Faults are scheduled at fixed points, not emergent; compensations
  are pre-written in the scenario, not derived by the agent.
- The action budget is enforced and unit-tested but never reached
  by any scenario; "continued with side effects" is defined but
  unpopulated in this dataset (every duplicate also breaks the
  final state).

Full limitations and recommendations: `docs/evaluation.md`.
