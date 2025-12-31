"""Sandboxed tools tests, including ledger, inventory, faults and idempotency."""

import pytest

from racrs.permissions import Action, Scope
from racrs.tools import Sandbox, ToolSet


def _tools(faults=None, **setup):
    sandbox = Sandbox.from_setup(setup)
    return ToolSet(sandbox, Scope(), faults=faults), sandbox


def test_ledger_transfer_and_balance():
    tools, sandbox = _tools(ledger={"acct:main": 1000, "acct:ops": 0})
    result, _ = tools.call(Action("ledger", "transfer", "acct:ops",
                                  {"from": "acct:main", "amount": 100}))
    assert result.ok
    assert sandbox.ledger == {"acct:main": 900, "acct:ops": 100}
    result, _ = tools.call(Action("ledger", "balance", "acct:ops"))
    assert result.ok and "BALANCE: acct:ops=100" in result.output


def test_ledger_insufficient_funds_fails_without_side_effect():
    tools, sandbox = _tools(ledger={"acct:main": 50, "acct:ops": 0})
    result, _ = tools.call(Action("ledger", "transfer", "acct:ops",
                                  {"from": "acct:main", "amount": 100}))
    assert not result.ok
    assert sandbox.ledger == {"acct:main": 50, "acct:ops": 0}


def test_inventory_reserve_release_order_get():
    tools, sandbox = _tools(inventory={"item:widget": 10})
    result, _ = tools.call(Action("inventory", "reserve", "item:widget", {"qty": 2}))
    assert result.ok and sandbox.inventory["item:widget"] == 8
    result, _ = tools.call(Action("inventory", "release", "item:widget", {"qty": 2}))
    assert result.ok and sandbox.inventory["item:widget"] == 10
    result, _ = tools.call(Action("inventory", "order", "item:widget", {"qty": 3}))
    assert result.ok and sandbox.inventory["item:widget"] == 7
    assert len(sandbox.orders) == 1 and sandbox.orders[0]["qty"] == 3
    result, _ = tools.call(Action("inventory", "get", "item:widget"))
    assert result.ok and "STOCK: item:widget=7" in result.output


def test_inventory_insufficient_stock_fails():
    tools, sandbox = _tools(inventory={"item:widget": 1})
    result, _ = tools.call(Action("inventory", "order", "item:widget", {"qty": 2}))
    assert not result.ok and sandbox.inventory["item:widget"] == 1
    assert sandbox.orders == []


def test_snapshot_and_initial_snapshot():
    tools, sandbox = _tools(
        ledger={"acct:main": 100, "acct:ops": 0},
        inventory={"item:widget": 5})
    tools.call(Action("ledger", "transfer", "acct:ops",
                      {"from": "acct:main", "amount": 40}))
    snap = sandbox.snapshot()
    assert snap["ledger"] == {"acct:main": 60, "acct:ops": 40}
    assert snap["orders"] == []
    initial = sandbox.initial_snapshot()
    assert initial["ledger"] == {"acct:main": 100, "acct:ops": 0}


def test_timeout_fault_then_success():
    tools, _ = _tools({"ledger:transfer:acct:ops":
                       {"fault": "timeout", "fail_times": 1}},
                      ledger={"acct:main": 100, "acct:ops": 0})
    action = Action("ledger", "transfer", "acct:ops",
                    {"from": "acct:main", "amount": 10})
    first, _ = tools.call(action)
    assert not first.ok and first.fault == "timeout"
    second, _ = tools.call(action)
    assert second.ok and second.fault == ""


def test_unavailable_fault_never_succeeds():
    tools, _ = _tools({"inventory:reserve:item:widget":
                       {"fault": "unavailable"}},
                      inventory={"item:widget": 10})
    action = Action("inventory", "reserve", "item:widget", {"qty": 1})
    for _ in range(3):
        result, _ = tools.call(action)
        assert not result.ok and result.fault == "unavailable"


def test_duplicate_fault_completes_but_reports_error():
    tools, sandbox = _tools({"ledger:transfer:acct:ops":
                             {"fault": "duplicate"}},
                            ledger={"acct:main": 100, "acct:ops": 0})
    action = Action("ledger", "transfer", "acct:ops",
                    {"from": "acct:main", "amount": 10})
    result, _ = tools.call(action)
    assert result.ok and result.fault == "duplicate"
    assert sandbox.ledger["acct:ops"] == 10  # it really completed
    # A second, unfaulted call executes again: the tool cannot tell.
    result, _ = tools.call(action)
    assert result.ok and sandbox.ledger["acct:ops"] == 20


def test_stale_fault_returns_setup_time_value():
    tools, _ = _tools({"ledger:balance:acct:ops":
                       {"fault": "stale", "fail_times": 1,
                        "output": "BALANCE: acct:ops=0"}},
                      ledger={"acct:main": 900, "acct:ops": 100})
    result, _ = tools.call(Action("ledger", "balance", "acct:ops"))
    assert result.ok and result.fault == "stale"
    assert result.output == "BALANCE: acct:ops=0"
    result, _ = tools.call(Action("ledger", "balance", "acct:ops"))
    assert result.ok and result.fault == "" and "BALANCE: acct:ops=100" in result.output


def test_stale_fault_without_explicit_output_uses_initial_value():
    tools, _ = _tools({"ledger:balance:acct:ops": {"fault": "stale", "fail_times": 1}},
                      ledger={"acct:main": 1000, "acct:ops": 0})
    tools.call(Action("ledger", "transfer", "acct:ops",
                      {"from": "acct:main", "amount": 100}))
    result, _ = tools.call(Action("ledger", "balance", "acct:ops"))
    assert result.ok and result.fault == "stale"
    assert result.output == "BALANCE: acct:ops=0"  # setup-time value


def test_incomplete_fault_truncates_and_marks():
    tools, _ = _tools({"file:read:/workspace/order.txt":
                       {"fault": "incomplete", "fail_times": 1}},
                      files={"/workspace/order.txt":
                             "ORDER-RECORD: 2 x item:widget, ref=ORD-100"})
    result, _ = tools.call(Action("file", "read", "/workspace/order.txt"))
    assert result.ok and result.fault == "incomplete"
    assert "[INCOMPLETE]" in result.output
    assert "ref=ORD-100" not in result.output
    result, _ = tools.call(Action("file", "read", "/workspace/order.txt"))
    assert result.ok and result.fault == "" and "ref=ORD-100" in result.output


def test_contradictory_fault_returns_wrong_value():
    tools, _ = _tools({"ledger:balance:acct:ops":
                       {"fault": "contradictory", "fail_times": 1,
                        "output": "BALANCE: acct:ops=900"}},
                      ledger={"acct:main": 900, "acct:ops": 100})
    result, _ = tools.call(Action("ledger", "balance", "acct:ops"))
    assert result.ok and result.fault == "contradictory"
    assert result.output == "BALANCE: acct:ops=900"


def test_idempotent_replay_does_not_re_execute():
    tools, sandbox = _tools(ledger={"acct:main": 100, "acct:ops": 0})
    action = Action("ledger", "transfer", "acct:ops",
                    {"from": "acct:main", "amount": 10,
                     "idempotency_key": "task-1:ledger:transfer:acct:ops"})
    first, _ = tools.call(action)
    assert first.ok and first.fault == ""
    second, _ = tools.call(action)
    assert second.ok and second.fault == "idempotent-replay"
    assert sandbox.ledger["acct:ops"] == 10  # executed once


def test_verification_reads_bypass_faults():
    tools, _ = _tools({"ledger:balance:acct:ops":
                       {"fault": "stale", "fail_times": 1,
                        "output": "BALANCE: acct:ops=0"}},
                      ledger={"acct:main": 900, "acct:ops": 100})
    result, _ = tools.call(Action("ledger", "balance", "acct:ops"),
                           faults=False)
    assert result.ok and result.fault == "" and "BALANCE: acct:ops=100" in result.output
    # The scheduled fault still fires on a normal call afterwards.
    result, _ = tools.call(Action("ledger", "balance", "acct:ops"))
    assert result.fault == "stale"


def test_boundary_denial_never_reaches_tool():
    tools, sandbox = _tools(ledger={"acct:main": 100, "acct:ops": 0})
    result, decision = tools.call(Action("ledger", "transfer", "acct:attacker",
                                         {"from": "acct:main", "amount": 10}))
    assert not result.ok and not decision.allowed
    assert sandbox.ledger == {"acct:main": 100, "acct:ops": 0}
