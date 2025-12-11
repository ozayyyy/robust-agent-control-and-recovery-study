"""Command line interface.

Usage:
  python -m racrs list [--scenarios DIR]
  python -m racrs run [--scenarios DIR] [--config NAME|all]
                     [--seeds 0,1,2] [--out DIR] [--traces DIR]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .agents import CONFIG_BY_NAME, CONFIGS
from .reporting import build_report, render_markdown, write_json
from .runner import run_all
from .scenario import Scenario


def _parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="racrs",
        description="Robust Agent Control and Recovery Study")
    sub = parser.add_subparsers(dest="command", required=True)
    list_cmd = sub.add_parser("list", help="list scenarios")
    list_cmd.add_argument("--scenarios", default="scenarios")
    run_cmd = sub.add_parser("run", help="run the study")
    run_cmd.add_argument("--scenarios", default="scenarios")
    run_cmd.add_argument("--config", default="all",
                         help="baseline, retry-only, state-aware, "
                         "policy-constrained, or all")
    run_cmd.add_argument("--seeds", default="0,1,2",
                         help="comma-separated seeds, e.g. 0,1,2")
    run_cmd.add_argument("--out", default=None,
                         help="directory for report.json and report.md")
    run_cmd.add_argument("--traces", default=None,
                         help="directory for per-run JSONL traces")
    return parser.parse_args(argv)


def _load(scenarios_dir: str) -> list[Scenario]:
    scenarios = Scenario.load_all(scenarios_dir)
    if not scenarios:
        raise SystemExit(f"no scenarios found in {scenarios_dir}")
    return scenarios


def main(argv=None) -> int:
    args = _parse_args(argv)
    if args.command == "list":
        for scenario in _load(args.scenarios):
            print(f"{scenario.id:28s} {scenario.category:22s} {scenario.title}")
        return 0
    scenarios = _load(args.scenarios)
    if args.config == "all":
        configs = list(CONFIGS)
    elif args.config in CONFIG_BY_NAME:
        configs = [CONFIG_BY_NAME[args.config]]
    else:
        raise SystemExit(f"unknown config {args.config!r}")
    try:
        seeds = tuple(int(s) for s in args.seeds.split(",") if s.strip())
    except ValueError:
        raise SystemExit(f"invalid --seeds value {args.seeds!r}")
    if not seeds:
        raise SystemExit("at least one seed is required")
    results = run_all(scenarios, configs, seeds=seeds)
    report = build_report(results, seed=seeds[0], seeds=seeds)
    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        write_json(report, out / "report.json")
        (out / "report.md").write_text(render_markdown(report),
                                        encoding="utf-8")
        print(f"wrote {out / 'report.json'} and {out / 'report.md'}")
    else:
        print(render_markdown(report))
    if args.traces:
        traces = Path(args.traces)
        traces.mkdir(parents=True, exist_ok=True)
        for result in results:
            name = (f"{result.scenario_id}--{result.config}"
                    f"--seed{result.seed}.jsonl")
            (traces / name).write_text(result.trace.to_jsonl(),
                                        encoding="utf-8")
        print(f"wrote {len(results)} traces to {traces}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
