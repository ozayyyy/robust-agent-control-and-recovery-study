"""Run the study with your own model as the planner, and write a report.

Usage:
  python scripts/run_real_models.py [--scenarios DIR] [--config NAME|all]
      [--seeds 0] [--out FILE] [--traces DIR]
      [--api-base-url URL] [--api-key KEY] [--model MODEL]

The model plans the steps; everything else is the same study: the
sandboxed tools, the permission checks, the approval gate, the
postconditions and the rule-based scoring. Settings come from the
flags, or from RACRS_API_BASE_URL / RACRS_API_KEY / RACRS_MODEL.
The API key is never written to the report, a trace, or the screen.

Real-model numbers need your own endpoint and key: this script does
not invent results. Without a base URL and a model it stops with a
clear message and writes nothing. With them it runs the study once
per configuration and seed (default: every configuration, seed 0
only — a real model costs one API call per planning step, so the
default keeps the run small; pass --seeds 0,1,2 for the full
three-seed run).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from racrs.agents import CONFIG_BY_NAME, CONFIGS  # noqa: E402
from racrs.model_adapter import (ApiModelAdapter, ApiSettingsError,  # noqa: E402
                                 resolve_api_settings)
from racrs.reporting import build_report, write_json  # noqa: E402
from racrs.runner import run_all  # noqa: E402
from racrs.scenario import Scenario  # noqa: E402

DEFAULT_OUT = "examples/real-model-report.json"


def _parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the RACRS study with a real model as planner")
    parser.add_argument("--scenarios", default="scenarios")
    parser.add_argument("--config", default="all",
                        help="baseline, retry-only, state-aware, "
                        "policy-constrained, or all")
    parser.add_argument("--seeds", default="0",
                        help="comma-separated seeds, e.g. 0 or 0,1,2")
    parser.add_argument("--out", default=DEFAULT_OUT,
                        help="report JSON to write "
                        f"(default: {DEFAULT_OUT})")
    parser.add_argument("--traces", default=None,
                        help="directory for per-run JSONL traces")
    parser.add_argument("--api-base-url", default=None,
                        help="chat API base URL (or set "
                        "RACRS_API_BASE_URL)")
    parser.add_argument("--api-key", default=None,
                        help="API key (or set RACRS_API_KEY); never "
                        "stored or printed")
    parser.add_argument("--model", default=None,
                        help="model name to ask for (or set RACRS_MODEL)")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = _parse_args(argv)
    try:
        settings = resolve_api_settings(base_url=args.api_base_url,
                                        api_key=args.api_key,
                                        model=args.model)
    except ApiSettingsError as exc:
        print(f"cannot run with a real model: {exc}", file=sys.stderr)
        print("No report was written. Set RACRS_API_BASE_URL and "
              "RACRS_MODEL (and RACRS_API_KEY if your endpoint needs "
              "one), or pass --api-base-url and --model.",
              file=sys.stderr)
        return 2
    root = Path(__file__).resolve().parent.parent
    scenarios = Scenario.load_all(root / args.scenarios)
    if not scenarios:
        print(f"no scenarios found in {args.scenarios}", file=sys.stderr)
        return 2
    if args.config == "all":
        configs = list(CONFIGS)
    elif args.config in CONFIG_BY_NAME:
        configs = [CONFIG_BY_NAME[args.config]]
    else:
        print(f"unknown config {args.config!r}", file=sys.stderr)
        return 2
    try:
        seeds = tuple(int(s) for s in args.seeds.split(",") if s.strip())
    except ValueError:
        print(f"invalid --seeds value {args.seeds!r}", file=sys.stderr)
        return 2
    if not seeds:
        print("at least one seed is required", file=sys.stderr)
        return 2

    def agent_factory(config, seed):
        return ApiModelAdapter(config, seed=seed,
                               base_url=settings["base_url"],
                               api_key=settings["api_key"],
                               model=settings["model"])

    results = run_all(scenarios, configs, seeds=seeds,
                      agent_factory=agent_factory)
    report = build_report(results, seed=seeds[0], seeds=seeds)
    # What produced these numbers. The key is never recorded.
    report["agent"] = {"kind": "api", "model": settings["model"],
                       "base_url": settings["base_url"]}
    report["note"] = (
        "Measured with a real model through the API adapter "
        f"({settings['model']}). These numbers replace nothing: the "
        "published simulated-agent results are in examples/report.json. "
        "Compare the two only as a definition check — the simulated "
        "runs measure four fixed policies, these runs measure one "
        "model's planning. No real-model numbers exist until this "
        "script is run with a real endpoint and key.")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    write_json(report, out)
    if args.traces:
        traces = Path(args.traces)
        traces.mkdir(parents=True, exist_ok=True)
        for result in results:
            name = (f"{result.scenario_id}--{result.config}"
                    f"--seed{result.seed}.jsonl")
            (traces / name).write_text(result.trace.to_jsonl(),
                                        encoding="utf-8")
    print(f"scenarios: {len(scenarios)}, configs: {len(configs)}, "
          f"seeds: {list(seeds)}, runs: {len(results)}")
    print(f"model: {settings['model']} via {settings['base_url']}")
    for name, m in report["metrics"]["configs"].items():
        print(f"{name:20s} task={m['task_success_rate']:.1%} "
              f"recovery={m['recovery_success_rate']:.1%} "
              f"dups/run={m['duplicates_per_run']:.2f} "
              f"calls={m['mean_tool_calls']:.1f}")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
