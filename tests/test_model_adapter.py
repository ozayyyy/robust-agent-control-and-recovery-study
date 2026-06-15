"""Model adapter tests. All offline: a local HTTP server stands in
for the chat API. No real API calls, no real keys."""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from racrs.agents import CONFIG_BY_NAME, SimulatedAgent
from racrs.cli import main
from racrs.model_adapter import (ApiModelAdapter, ApiSettingsError,
                                 resolve_api_settings)
from racrs.permissions import Action
from racrs.reporting import build_report, render_markdown
from racrs.runner import run_scenario
from racrs.scenario import Scenario

ROOT = Path(__file__).resolve().parent.parent
KEY = "sk-secret-test-key-123"


class _Handler(BaseHTTPRequestHandler):
    """Canned chat-completions endpoint. Class attributes are reset
    before every test by the fixture."""

    status = 200
    body = b"{}"
    delay = 0.0
    requests = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        _Handler.requests.append({
            "headers": dict(self.headers),
            "body": json.loads(raw) if raw else None,
        })
        if _Handler.delay:
            time.sleep(_Handler.delay)
        try:
            self.send_response(_Handler.status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(_Handler.body)))
            self.end_headers()
            self.wfile.write(_Handler.body)
        except (BrokenPipeError, ConnectionResetError):
            pass  # the test client gave up (e.g. timeout test)

    def log_message(self, *args):
        pass


@pytest.fixture
def api_server():
    _Handler.status = 200
    _Handler.body = b"{}"
    _Handler.delay = 0.0
    _Handler.requests = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


def _url(server):
    return f"http://127.0.0.1:{server.server_address[1]}"


def _reply(content):
    return json.dumps(
        {"choices": [{"message": {"content": content}}]}).encode()


def _adapter(server, config="state-aware", **kwargs):
    kwargs.setdefault("api_key", KEY)
    kwargs.setdefault("model", "test-model")
    return ApiModelAdapter(CONFIG_BY_NAME[config], seed=0,
                           base_url=_url(server), **kwargs)


def _scenario(name="benign-01"):
    scenario = Scenario.load(ROOT / "scenarios" / f"{name}.json")
    assert scenario.id == name
    return scenario


def test_happy_path_returns_model_actions(api_server):
    _Handler.body = _reply(json.dumps([
        {"tool": "file", "op": "read", "target": "/workspace/notes.txt",
         "args": {}},
        {"tool": "kv", "op": "get", "target": "task:current:note",
         "args": {}}]))
    adapter = _adapter(api_server)
    actions = adapter.plan_legitimate(_scenario())
    assert [a.key() for a in actions] == [
        "file:read:/workspace/notes.txt", "kv:get:task:current:note"]
    assert adapter.last_error is None
    request = _Handler.requests[0]
    assert request["body"]["model"] == "test-model"
    assert request["body"]["messages"][0]["role"] == "system"
    assert request["body"]["messages"][1]["role"] == "user"
    assert "ledger" in request["body"]["messages"][0]["content"]
    assert "inventory" in request["body"]["messages"][0]["content"]
    assert request["headers"]["Authorization"] == f"Bearer {KEY}"


def test_markdown_fences_tolerated(api_server):
    content = ("```json\n"
               '[{"tool": "file", "op": "read", '
               '"target": "/workspace/notes.txt", "args": {}}]\n```')
    _Handler.body = _reply(content)
    actions = _adapter(api_server).plan_legitimate(_scenario())
    assert [a.key() for a in actions] == ["file:read:/workspace/notes.txt"]


def test_malformed_response_body_returns_empty_plan(api_server):
    _Handler.body = b"this is not json"
    adapter = _adapter(api_server)
    assert adapter.plan_legitimate(_scenario()) == []
    assert adapter.last_error is not None
    assert "failed" in adapter.last_error


def test_http_500_returns_empty_plan(api_server):
    _Handler.status = 500
    _Handler.body = json.dumps({"error": "boom"}).encode()
    adapter = _adapter(api_server)
    assert adapter.plan_legitimate(_scenario()) == []
    assert adapter.last_error is not None


def test_timeout_returns_empty_plan(api_server):
    _Handler.delay = 2.0
    _Handler.body = _reply("[]")
    adapter = _adapter(api_server, timeout=0.2)
    assert adapter.plan_legitimate(_scenario()) == []
    assert adapter.last_error is not None


def test_unknown_tool_and_op_dropped(api_server):
    _Handler.body = _reply(json.dumps([
        {"tool": "file", "op": "read", "target": "/workspace/notes.txt",
         "args": {}},
        {"tool": "rocket", "op": "launch", "target": "moon", "args": {}},
        {"tool": "file", "op": "explode", "target": "/workspace/x",
         "args": {}},
        {"tool": "file", "op": "read", "target": 42, "args": {}},
        "not even an object",
    ]))
    actions = _adapter(api_server).plan_legitimate(_scenario())
    assert [a.key() for a in actions] == ["file:read:/workspace/notes.txt"]


def test_env_var_configuration(monkeypatch):
    monkeypatch.setenv("RACRS_API_BASE_URL", "http://env.example/v1")
    monkeypatch.setenv("RACRS_API_KEY", "env-key")
    monkeypatch.setenv("RACRS_MODEL", "env-model")
    adapter = ApiModelAdapter(CONFIG_BY_NAME["baseline"])
    assert adapter.settings == {
        "base_url": "http://env.example/v1", "api_key": "env-key",
        "model": "env-model"}
    # An explicit argument wins over the environment.
    settings = resolve_api_settings(base_url="http://flag.example/v1")
    assert settings["base_url"] == "http://flag.example/v1"
    assert settings["model"] == "env-model"


def test_missing_base_url_and_model_errors(monkeypatch):
    for var in ("RACRS_API_BASE_URL", "RACRS_API_KEY", "RACRS_MODEL"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(ApiSettingsError, match="RACRS_API_BASE_URL"):
        ApiModelAdapter(CONFIG_BY_NAME["baseline"])
    monkeypatch.setenv("RACRS_API_BASE_URL", "http://env.example/v1")
    with pytest.raises(ApiSettingsError, match="RACRS_MODEL"):
        ApiModelAdapter(CONFIG_BY_NAME["baseline"])


def test_cli_api_without_base_url(monkeypatch):
    for var in ("RACRS_API_BASE_URL", "RACRS_API_KEY", "RACRS_MODEL"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(SystemExit, match="RACRS_API_BASE_URL"):
        main(["run", "--scenarios", str(ROOT / "scenarios"),
              "--agent", "api", "--config", "baseline", "--seeds", "0"])


def test_plan_after_observation_includes_observations(api_server):
    _Handler.body = _reply("[]")
    adapter = _adapter(api_server)
    assert adapter.plan_after_observation(
        _scenario(), ["ledger balance is 100"]) == []
    user_text = _Handler.requests[0]["body"]["messages"][1]["content"]
    assert "ledger balance is 100" in user_text


def test_retry_refusal_and_idempotency_match_simulated():
    scenario = Scenario.load(ROOT / "scenarios" / "rollback-01.json")
    step_action = scenario.plan_steps[0].action
    effect = Action(tool="ledger", op="transfer", target="acct:main",
                    args={"from": "acct:main", "to": "acct:ops"})
    for name in ("baseline", "retry-only", "state-aware",
                 "policy-constrained"):
        config = CONFIG_BY_NAME[name]
        api = ApiModelAdapter(config, base_url="http://127.0.0.1:9",
                              model="test-model")
        sim = SimulatedAgent(config)
        for fault in ("timeout", "malformed", "unavailable", "duplicate",
                      "postcondition-failed"):
            assert api.should_retry(effect, fault, False, 0) == \
                sim.should_retry(effect, fault, False, 0)
            assert api.should_retry(effect, fault, True, 0) == \
                sim.should_retry(effect, fault, True, 0)
        assert api.should_refuse(scenario) == sim.should_refuse(scenario)
        assert api.compensation_for(step_action, scenario) == \
            sim.compensation_for(step_action, scenario)
        assert api.idempotency_key(effect, scenario) == \
            sim.idempotency_key(effect, scenario)


def test_key_never_in_trace_report_or_error(api_server):
    scenario = _scenario()
    _Handler.body = _reply(json.dumps(
        [a.to_dict() for a in scenario.legitimate_steps]))
    adapter = _adapter(api_server)
    result = run_scenario(scenario, CONFIG_BY_NAME["state-aware"],
                          agent=adapter, seed=0)
    assert KEY not in result.trace.to_jsonl()
    report = build_report([result])
    assert KEY not in json.dumps(report)
    assert KEY not in render_markdown(report)
    # A failed call must not leak it either.
    _Handler.status = 500
    adapter.plan_legitimate(scenario)
    assert adapter.last_error is not None
    assert KEY not in adapter.last_error


def test_cli_help_shows_new_flags(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["run", "--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "--agent" in out
    assert "--api-base-url" in out
    assert "--model" in out
