"""Run the full study and write the measured results.

Usage: python scripts/evaluate.py [--scenarios DIR] [--seeds 0,1,2]
Writes examples/report.json, examples/report.md and per-run traces
under examples/traces/ (seed 0 runs only, to keep the example set
small — the full run is reproduced by the CLI with --traces).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from racrs.agents import CONFIGS  # noqa: E402
from racrs.reporting import build_report, render_markdown, write_json  # noqa: E402
from racrs.runner import run_all  # noqa: E402
from racrs.scenario import Scenario  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the RACRS evaluation")
    parser.add_argument("--scenarios", default="scenarios")
    parser.add_argument("--seeds", default="0,1,2")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    seeds = tuple(int(s) for s in args.seeds.split(",") if s.strip())
    scenarios = Scenario.load_all(root / args.scenarios)
    results = run_all(scenarios, list(CONFIGS), seeds=seeds)
    report = build_report(results, seed=seeds[0], seeds=seeds)
    examples = root / "examples"
    examples.mkdir(exist_ok=True)
    write_json(report, examples / "report.json")
    (examples / "report.md").write_text(render_markdown(report),
                                         encoding="utf-8")
    traces = examples / "traces"
    traces.mkdir(exist_ok=True)
    for result in results:
        if result.seed != seeds[0]:
            continue
        name = f"{result.scenario_id}--{result.config}.jsonl"
        (traces / name).write_text(result.trace.to_jsonl(), encoding="utf-8")
    print(f"scenarios: {len(scenarios)}, configs: {len(CONFIGS)}, "
          f"seeds: {list(seeds)}, runs: {len(results)}")
    for name, m in report["metrics"]["configs"].items():
        print(f"{name:20s} task={m['task_success_rate']:.1%} "
              f"recovery={m['recovery_success_rate']:.1%} "
              f"clean_abort={m['clean_abort_rate']:.1%} "
              f"dups/run={m['duplicates_per_run']:.2f} "
              f"calls={m['mean_tool_calls']:.1f} "
              f"consistency={m['run_to_run_consistency']:.1%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
