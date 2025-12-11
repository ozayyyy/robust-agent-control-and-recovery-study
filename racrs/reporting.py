"""Reporting: JSON and Markdown evaluation reports."""

from __future__ import annotations

import json

from .arsb_reference import (ARSB_HEADLINE, ARSB_METHOD,
                             ARSB_RECOVERY_BY_CONFIG)
from .runner import RunResult
from .scoring import score


def build_report(results: list[RunResult], seed: int = 0,
                 seeds: tuple[int, ...] = (0, 1, 2)) -> dict:
    metrics = score(results)
    return {
        "seeds": list(seeds),
        "seed": seed,
        "runs": [r.to_dict() for r in results],
        "metrics": metrics,
        "arsb_reference": {
            "method": ARSB_METHOD,
            "headline": ARSB_HEADLINE,
            "recovery_by_config": ARSB_RECOVERY_BY_CONFIG,
        },
    }


def write_json(report: dict, path) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, sort_keys=True)


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def render_markdown(report: dict) -> str:
    metrics = report["metrics"]["configs"]
    names = sorted(metrics)
    lines = [
        "# Robust Agent Control and Recovery Study — Results",
        "",
        f"Runs: {report['metrics']['total_runs']} "
        f"(seeds {', '.join(str(s) for s in report['seeds'])}).",
        "Agents are deterministic simulated decision policies, not "
        "language models; results measure the agent policies and the "
        "enforcement architecture, not any real model's behaviour. "
        "Scoring is rule-based; no LLM judge is used. Recovery means "
        "the task completed after a fault fired, with no duplicate "
        "actions, no unintended side effects and the expected final "
        "state — completing the task with a duplicate or a side "
        "effect is counted separately, not as a recovery.",
        "",
        "## Headline metrics",
        "",
        "| Configuration | Task success | Recovery success | Continued with side effects | "
        "Clean abort | Duplicates / run | Unintended / run | Mean tool calls | "
        "Mean retries | Mean approvals denied | State match | Run-to-run consistency |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for name in names:
        m = metrics[name]
        lines.append(
            f"| {name} | {_pct(m['task_success_rate'])} | "
            f"{_pct(m['recovery_success_rate'])} | "
            f"{_pct(m['continued_with_side_effects_rate'])} | "
            f"{_pct(m['clean_abort_rate'])} | "
            f"{m['duplicates_per_run']:.2f} | "
            f"{m['unintended_per_run']:.2f} | "
            f"{m['mean_tool_calls']:.1f} | "
            f"{m['mean_retries']:.2f} | "
            f"{m['mean_approvals_denied']:.2f} | "
            f"{_pct(m['state_match_rate'])} | "
            f"{_pct(m['run_to_run_consistency'])} |")
    lines += ["", "## Task success by category", "",
              "| Category | " + " | ".join(names) + " |",
              "|---|" + "---|" * len(names)]
    categories = sorted({c for m in metrics.values()
                         for c in m["by_category"]})
    for category in categories:
        cells = [_pct(metrics[name]["by_category"][category]["task_success_rate"])
                 if category in metrics[name]["by_category"] else "-"
                 for name in names]
        lines.append(f"| {category} | " + " | ".join(cells) + " |")
    lines += ["", "## Recovery success by fault class", "",
              "| Fault | " + " | ".join(names) + " |",
              "|---|" + "---|" * len(names)]
    faults = sorted({f for m in metrics.values() for f in m["by_fault"]})
    for fault in faults:
        cells = [_pct(metrics[name]["by_fault"][fault]["recovery_success_rate"])
                 if fault in metrics[name]["by_fault"] else "-"
                 for name in names]
        lines.append(f"| {fault} | " + " | ".join(cells) + " |")
    lines += ["", "## Duplicates per run by fault class", "",
              "| Fault | " + " | ".join(names) + " |",
              "|---|" + "---|" * len(names)]
    for fault in faults:
        cells = [f"{metrics[name]['by_fault'][fault]['duplicates_per_run']:.2f}"
                 if fault in metrics[name]["by_fault"] else "-"
                 for name in names]
        lines.append(f"| {fault} | " + " | ".join(cells) + " |")
    lines += ["", "## Comparison with ARSB (published results)", "",
              "ARSB's headline numbers (37 scenarios v1.0 x 4 configs, "
              "seeds 0, 1, 2, 444 runs) are reference data, not measured "
              "here. ARSB's recovery rate is measured on its 4 "
              "tool-error-recovery scenarios only (timeout, malformed, "
              "unavailable, duplicate); RACRS measures the same quantity "
              "over 7 fault classes plus partial failure, rollback and "
              "confirmation, so the two recovery rates are the same "
              "definition on different fault coverage — the comparison "
              "is a definition check, not a ranking.",
              "",
              "| Configuration | ARSB recovery | RACRS recovery success |",
              "|---|---|---|"]
    for name in ("baseline", "retry-only", "state-aware", "policy-constrained"):
        if name not in metrics:
            continue
        ref = report["arsb_reference"]["recovery_by_config"].get(name)
        ref_cell = _pct(ref) if ref is not None else "n/a (no ARSB equivalent)"
        lines.append(
            f"| {name} | {ref_cell} | "
            f"{_pct(metrics[name]['recovery_success_rate'])} |")
    lines += ["", "## Reading the results", "",
              "- Baseline never retries and never verifies: it survives "
              "a one-off fault only when the fault does not matter to "
              "the outcome, and it follows a stale or contradictory "
              "observation into a duplicate action.",
              "- Retry-only fixes timeouts and malformed responses, but "
              "it retries an error reported after an action already "
              "completed, so it is the only strategy that duplicates a "
              "delivery — retrying without verifying is worse than not "
              "retrying, for that fault class.",
              "- State-aware verifies each step's postcondition before "
              "accepting it and uses idempotency keys, so it recovers "
              "from transient faults without duplicating, and it aborts "
              "and compensates instead of leaving the system in a "
              "half-finished state.",
              "- Policy-constrained adds tool-side enforcement, the "
              "approval gate and an action budget to the state-aware "
              "policy. It pays for that with the confirmation scenario: "
              "a large payment without pre-approval is blocked, so the "
              "task fails cleanly instead of completing. That is the "
              "control / usefulness trade-off, measured.",
              "- Run-to-run consistency is 100% for every strategy: the "
              "policies are deterministic and the fault schedule is "
              "fixed per scenario, so repeated seeds reproduce the same "
              "runs. Variability in this study is across fault classes "
              "and strategies, not across seeds.",
              ""]
    return "\n".join(lines)
