"""Permission model tests, including the RACRS extensions."""

from racrs.permissions import (CONSEQUENTIAL_OPS, Action, ApprovalGate,
                               Scope, check_boundary)


def test_action_key_and_round_trip():
    action = Action("ledger", "transfer", "acct:ops",
                    {"from": "acct:main", "amount": 100})
    assert action.key() == "ledger:transfer:acct:ops"
    assert Action.from_dict(action.to_dict()) == action


def test_ledger_transfer_inside_scope_allowed():
    scope = Scope()
    action = Action("ledger", "transfer", "acct:ops",
                    {"from": "acct:main", "amount": 100})
    decision = check_boundary(action, scope)
    assert decision.allowed


def test_ledger_transfer_to_unknown_account_denied():
    scope = Scope()
    action = Action("ledger", "transfer", "acct:attacker",
                    {"from": "acct:main", "amount": 100})
    decision = check_boundary(action, scope)
    assert not decision.allowed
    assert decision.rule == "account-out-of-scope"


def test_ledger_transfer_from_unknown_account_denied():
    scope = Scope()
    action = Action("ledger", "transfer", "acct:ops",
                    {"from": "acct:attacker", "amount": 100})
    assert not check_boundary(action, scope).allowed


def test_inventory_item_out_of_scope_denied():
    scope = Scope()
    action = Action("inventory", "order", "item:rocket", {"qty": 1})
    decision = check_boundary(action, scope)
    assert not decision.allowed
    assert decision.rule == "item-out-of-scope"


def test_consequential_ops_include_transfer_reserve_order():
    assert {"transfer", "reserve", "order"} <= CONSEQUENTIAL_OPS
    # 7/8 consequential ops are unchanged.
    assert {"write", "delete", "send", "spend", "publish", "put"} \
        <= CONSEQUENTIAL_OPS


def test_scope_round_trip_with_new_fields():
    scope = Scope()
    restored = Scope.from_dict(scope.to_dict())
    assert restored.allowed_accounts == scope.allowed_accounts
    assert restored.allowed_items == scope.allowed_items
    assert restored.allowed_tools == scope.allowed_tools


def test_scope_from_7_format_dict_gets_defaults():
    # A 7/8-format scope has no allowed_accounts / allowed_items.
    old = {"allowed_paths": ["/workspace/"],
           "allowed_hosts": ["example.internal"],
           "allowed_classifications": ["public", "internal"],
           "allowed_tools": ["file", "web", "kv", "shell"],
           "allowed_ops": {},
           "kv_namespaces": ["task:current"]}
    scope = Scope.from_dict(old)
    assert scope.allowed_accounts == ("acct:main", "acct:ops", "acct:vendor")
    assert scope.allowed_items == ("item:widget", "item:gadget")


def test_approval_gate_preapproved_and_denied():
    gate = ApprovalGate(mode="gate",
                        preapproved=("ledger:transfer:acct:ops",))
    ok = Action("ledger", "transfer", "acct:ops",
                {"from": "acct:main", "amount": 100})
    assert gate.request(ok).allowed
    other = Action("ledger", "transfer", "acct:vendor",
                   {"from": "acct:main", "amount": 100})
    assert not gate.request(other).allowed


def test_approval_gate_threshold_approves_small_amounts():
    gate = ApprovalGate(mode="gate", preapproved=(),
                        confirmation_threshold=1000)
    small = Action("ledger", "transfer", "acct:vendor",
                   {"from": "acct:main", "amount": 500})
    assert gate.request(small).allowed
    assert gate.request(small).rule == "below-confirmation-threshold"
    large = Action("ledger", "transfer", "acct:vendor",
                   {"from": "acct:main", "amount": 5000})
    assert not gate.request(large).allowed


def test_approval_gate_no_threshold_is_7_behaviour():
    gate = ApprovalGate(mode="gate", preapproved=())
    small = Action("ledger", "transfer", "acct:vendor",
                   {"from": "acct:main", "amount": 1})
    assert not gate.request(small).allowed


def test_approval_gate_auto_and_non_consequential():
    gate = ApprovalGate(mode="auto", preapproved=())
    assert gate.request(Action("ledger", "transfer", "acct:ops",
                               {"from": "acct:main", "amount": 1})).allowed
    assert gate.request(Action("ledger", "balance", "acct:ops")).allowed
