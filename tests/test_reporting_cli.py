"""Reporting and CLI tests."""

from pathlib import Path

from racrs.agents import CONFIGS
from racrs.cli import main
from racrs.reporting import build_report, render_markdown
from racrs.runner import run_all
from racrs.scenario import Scenario

ROOT = Path(__file__).resolve().parent.parent


def _small_run():
    scenarios = Scenario.load_all(ROOT / "scenarios")[:2]
    return run_all(scenarios, list(CONFIGS), seeds=(0,))


def test_report_contains_headline_and_fault_tables():
    report = build_report(_small_run())
    assert report["metrics"]["total_runs"] == 8
    assert "arsb_reference" in report
    text = render_markdown(report)
    assert "Recovery success" in text
    assert "Recovery success by fault class" in text
    assert "Comparison with ARSB" in text
    assert "baseline" in text and "policy-constrained" in text


def test_cli_list(capsys):
    assert main(["list", "--scenarios", str(ROOT / "scenarios")]) == 0
    out = capsys.readouterr().out
    assert "benign-01" in out and "rollback-01" in out


def test_cli_run_writes_reports(tmp_path):
    out = tmp_path / "out"
    traces = tmp_path / "traces"
    assert main(["run", "--scenarios", str(ROOT / "scenarios"),
                 "--config", "baseline", "--seeds", "0",
                 "--out", str(out), "--traces", str(traces)]) == 0
    assert (out / "report.json").exists()
    assert (out / "report.md").exists()
    assert len(list(traces.glob("*.jsonl"))) == 13


def test_cli_unknown_config_exits():
    import pytest
    with pytest.raises(SystemExit, match="unknown config"):
        main(["run", "--scenarios", str(ROOT / "scenarios"),
              "--config", "no-such-config"])
