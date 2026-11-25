"""Sandboxed tools. All state is in-memory and synthetic.

Mirrors ``arsb.tools``: the same ``Sandbox`` and ``ToolSet``, the
same file / web / key-value / shell tools, the same simulated shell
allowlist, the same fault-injection shape (``faults`` mapping action
key to ``{"fault", "fail_times"}``). No tool touches the real
filesystem, network or shell.

RACRS extensions, all documented in ``docs/architecture.md``:

- Two new tools over the same sandbox: ``ledger`` (simulated
  payment/transfer store: accounts with integer balances) and
  ``inventory`` (simulated stock/order store: item quantities,
  reservations and an order list). Both are deterministic and
  in-memory; ``Sandbox.snapshot()`` captures the whole state so the
  runner can compare it against a scenario's expected final state.
- Three new observation faults, for reads only: ``stale`` (the read
  returns the value the target held at setup time, i.e. before the
  latest write), ``incomplete`` (the read returns the first half of
  the true output) and ``contradictory`` (the read returns a value
  that contradicts the true one). A fault spec may carry an explicit
  ``output`` that is returned instead of the computed one. Like
  ARSB's ``duplicate`` fault, an observation fault completes the
  call (``ok=True``) with a wrong output and a ``fault`` field — the
  call succeeded, the observation is wrong, and only an agent that
  verifies what it observed can tell.
- One multiplicative fault, ``gain``: the call completes but a
  quantity is scaled by the spec's ``factor`` (default 2) — a
  ledger transfer moves ``amount * factor``, an inventory
  reserve/order takes ``qty * factor``, a balance/stock read
  reports a scaled value. It is the paper's offset-vs-gain
  distinction (see ``docs/counterfactual.md``): an offset fault
  adds a fixed error, a gain fault multiplies the command, and a
  retry cannot fix it — the wrong amount is already moved. Only
  a compensation or a clean abort can undo it.
- Idempotency: an action whose ``args`` carry an
  ``idempotency_key`` is executed at most once per run. A repeat
  call with the same key returns the stored result with
  ``fault="idempotent-replay"`` and does not touch state again.
  This is the tool-side half of the state-aware agent's duplicate
  protection; the agent-side half is verifying before retrying.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .permissions import (Action, PolicyDecision, Scope, check_boundary,
                          PUBLIC)


@dataclass
class ToolResult:
    """Outcome of one tool call."""

    ok: bool
    output: str
    denied_reason: str = ""
    classification: str = PUBLIC
    fault: str = ""  # Which fault fired, "" if none.

    def to_dict(self) -> dict:
        return {"ok": self.ok, "output": self.output,
                "denied_reason": self.denied_reason,
                "classification": self.classification,
                "fault": self.fault}


@dataclass
class FileEntry:
    content: str
    classification: str = PUBLIC


# Commands the simulated shell may run, and their canned outputs.
# Anything else is refused at the boundary; nothing is ever executed.
SHELL_ALLOWLIST = {"echo", "date", "pwd", "whoami", "ls"}

# Fault names and the failure text each one produces.
FAULT_MESSAGES = {
    "timeout": "tool timed out",
    "malformed": "tool returned a malformed response",
    "unavailable": "tool unavailable",
    "duplicate": "ERROR: delivery uncertain — action may not have completed",
    "gain": "tool returned a scaled quantity",
}

# Faults that corrupt an observation instead of failing the call.
# They only apply to read operations; the scenario loader enforces that.
OBSERVATION_FAULTS = ("stale", "incomplete", "contradictory")

# Read operations, by tool: the only operations observation faults
# may be attached to.
READ_OPS = {
    "file": {"read"},
    "kv": {"get"},
    "ledger": {"balance"},
    "inventory": {"get"},
}


class Sandbox:
    """The controlled environment: virtual files, canned web,
    namespaced KV, ledger accounts, inventory stock and orders."""

    def __init__(self, files: dict | None = None, pages: dict | None = None,
                 kv: dict | None = None, ledger: dict | None = None,
                 inventory: dict | None = None):
        # files: path -> FileEntry (or plain string, treated as public)
        self.files: dict[str, FileEntry] = {}
        for path, entry in (files or {}).items():
            if isinstance(entry, FileEntry):
                self.files[path] = entry
            elif isinstance(entry, dict):
                self.files[path] = FileEntry(
                    content=entry.get("content", ""),
                    classification=entry.get("classification", PUBLIC))
            else:
                self.files[path] = FileEntry(content=str(entry))
        # pages: url -> body (untrusted content by definition)
        self.pages: dict[str, str] = dict(pages or {})
        # kv: key -> value; keys are namespaced, e.g. task:current:note
        self.kv: dict[str, str] = dict(kv or {})
        # ledger: account -> integer balance
        self.ledger: dict[str, int] = {k: int(v) for k, v in (ledger or {}).items()}
        # inventory: item -> integer stock on hand
        self.inventory: dict[str, int] = {k: int(v)
                                          for k, v in (inventory or {}).items()}
        # orders: list of {"item", "qty", "order_id"} in creation order
        self.orders: list[dict] = []
        # reservations: list of {"item", "qty"} currently held
        self.reservations: list[dict] = []
        self._order_counter = 0
        # Values held at setup time, for the stale observation fault:
        # a stale read returns the setup-time value.
        self._initial_files = {p: e.content for p, e in self.files.items()}
        self._initial_kv = dict(self.kv)
        self._initial_ledger = dict(self.ledger)
        self._initial_inventory = dict(self.inventory)

    @classmethod
    def from_setup(cls, setup: dict) -> "Sandbox":
        return cls(files=setup.get("files", {}), pages=setup.get("pages", {}),
                   kv=setup.get("kv", {}), ledger=setup.get("ledger", {}),
                   inventory=setup.get("inventory", {}))

    def snapshot(self) -> dict:
        """The whole observable state, for final-state comparison."""
        return {
            "files": {p: e.content for p, e in sorted(self.files.items())},
            "kv": dict(sorted(self.kv.items())),
            "ledger": dict(sorted(self.ledger.items())),
            "inventory": dict(sorted(self.inventory.items())),
            "orders": [dict(o) for o in self.orders],
            "reservations": [dict(r) for r in self.reservations],
        }

    def initial_snapshot(self) -> dict:
        """The state as set up, before any tool call."""
        return {
            "files": dict(self._initial_files),
            "kv": dict(self._initial_kv),
            "ledger": dict(self._initial_ledger),
            "inventory": dict(self._initial_inventory),
            "orders": [],
            "reservations": [],
        }

    def initial_value(self, action: Action) -> str:
        """The setup-time value a stale read of this action returns."""
        if action.tool == "file":
            return self._initial_files.get(action.target, "")
        if action.tool == "kv":
            return self._initial_kv.get(action.target, "")
        if action.tool == "ledger":
            return f"BALANCE: {action.target}={self._initial_ledger.get(action.target, 0)}"
        if action.tool == "inventory":
            return f"STOCK: {action.target}={self._initial_inventory.get(action.target, 0)}"
        return ""


class ToolSet:
    """All tools, sharing one sandbox and one scope."""

    def __init__(self, sandbox: Sandbox, scope: Scope,
                 faults: dict | None = None):
        self.sandbox = sandbox
        self.scope = scope
        # faults: action key -> {"fault": name, "fail_times": n, "output": ...}
        self.faults = dict(faults or {})
        self._attempts: dict[str, int] = {}
        # idempotency_key -> stored ToolResult of the first execution.
        self._idempotent: dict[str, ToolResult] = {}

    def call(self, action: Action, faults: bool = True
             ) -> tuple[ToolResult, PolicyDecision]:
        """Run one action: boundary check first, tool second.

        Returns (result, decision). A denied action never reaches the
        tool implementation, so the tool cannot be tricked into
        completing it. A fault fires only after the boundary allows
        the action. An idempotent replay never re-executes.

        ``faults=False`` skips fault injection: the runner uses it
        for verification reads, so a scheduled fault lands on the
        plan step it is defined for (the observation the agent acts
        on), not on the agent's internal check of that step.
        """
        classification = self._classification_of(action)
        decision = check_boundary(action, self.scope, classification)
        if not decision.allowed:
            return ToolResult(False, "", denied_reason=decision.reason), decision
        handler = getattr(self, f"_do_{action.tool}", None)
        if handler is None:
            decision = PolicyDecision(False, f"no handler for {action.tool!r}",
                                      "unknown-tool")
            return ToolResult(False, "", denied_reason=decision.reason), decision
        key = action.key()
        idem_key = action.args.get("idempotency_key")
        if idem_key is not None and idem_key in self._idempotent:
            stored = self._idempotent[idem_key]
            return ToolResult(True, stored.output, fault="idempotent-replay",
                              classification=stored.classification), decision
        spec = self.faults.get(key) if faults else None
        if spec is not None:
            fault = spec.get("fault", "")
            fail_times = int(spec.get("fail_times", 1))
            attempt = self._attempts.get(key, 0)
            self._attempts[key] = attempt + 1
            if fault == "duplicate" and attempt == 0:
                # Completes, but reports an error. A retry duplicates it.
                result = handler(action)
                if result.ok:
                    self._store_idempotent(idem_key, result)
                    return ToolResult(True, FAULT_MESSAGES["duplicate"],
                                      fault="duplicate",
                                      classification=result.classification), decision
                return result, decision
            if fault in OBSERVATION_FAULTS and attempt < fail_times:
                # Completes with a wrong observation.
                result = handler(action)
                if not result.ok:
                    return result, decision
                output = spec.get("output")
                if output is None:
                    if fault == "stale":
                        output = self.sandbox.initial_value(action)
                    elif fault == "incomplete":
                        output = (result.output[:len(result.output) // 2]
                                  + " [INCOMPLETE]")
                    else:  # contradictory
                        output = f"CONTRADICTORY: {result.output}"
                return ToolResult(True, str(output), fault=fault,
                                  classification=result.classification), decision
            if fault == "gain" and attempt < fail_times:
                # Multiplicative fault (see _gain_result): the call
                # completes, but a quantity is scaled — a charge
                # multiplied, a stock count inflated. Unlike the
                # observation faults it can hit effectful actions.
                return self._gain_result(action, spec), decision
            if fault == "unavailable" or attempt < fail_times:
                return (ToolResult(False, "",
                                   denied_reason=FAULT_MESSAGES.get(
                                       fault, "tool error"),
                                   fault=fault), decision)
        result = handler(action)
        self._store_idempotent(idem_key, result)
        return result, decision

    def _store_idempotent(self, idem_key, result: ToolResult) -> None:
        if idem_key is not None and result.ok and idem_key not in self._idempotent:
            self._idempotent[idem_key] = result

    def _gain_result(self, action: Action, spec: dict) -> ToolResult:
        """Multiplicative fault: scale the action's quantity.

        The fault spec carries ``factor`` (default 2). On an
        effectful action the quantity is multiplied before the
        tool runs: a ledger transfer moves ``amount * factor``, an
        inventory reserve/order takes ``qty * factor``. On a read
        the returned number is multiplied instead (a balance or
        stock read that reports a scaled value). The call
        completes — the fault is in what it did, not in whether
        it ran — so a retry cannot fix it by itself: the wrong
        amount is already moved, and only a compensation (or a
        clean abort) can undo it. Actions with no scalable
        quantity are unaffected: the fault does not fire and the
        call runs normally. A factor of 1 scales nothing, so the
        fault does not fire either.
        """
        try:
            factor = int(spec.get("factor", 2))
        except (TypeError, ValueError):
            factor = 2
        if factor == 1:
            return self._do_dispatch(action)
        if action.tool == "ledger" and action.op == "transfer":
            try:
                amount = int(action.args.get("amount", 0))
            except (TypeError, ValueError):
                return self._do_dispatch(action)
            scaled = Action(action.tool, action.op, action.target,
                            {**action.args, "amount": amount * factor})
            result = self._do_ledger(scaled)
            self._store_idempotent(action.args.get("idempotency_key"), result)
            return ToolResult(result.ok, result.output,
                              denied_reason=result.denied_reason,
                              fault="gain",
                              classification=result.classification)
        if action.tool == "inventory" and action.op in ("reserve", "order"):
            try:
                qty = int(action.args.get("qty", 1))
            except (TypeError, ValueError):
                return self._do_dispatch(action)
            scaled = Action(action.tool, action.op, action.target,
                            {**action.args, "qty": qty * factor})
            result = self._do_inventory(scaled)
            self._store_idempotent(action.args.get("idempotency_key"), result)
            return ToolResult(result.ok, result.output,
                              denied_reason=result.denied_reason,
                              fault="gain",
                              classification=result.classification)
        if action.tool == "ledger" and action.op == "balance":
            result = self._do_ledger(action)
            if not result.ok:
                return result
            balance = self.sandbox.ledger.get(action.target, 0) * factor
            return ToolResult(True, f"BALANCE: {action.target}={balance}",
                              fault="gain",
                              classification=result.classification)
        if action.tool == "inventory" and action.op == "get":
            result = self._do_inventory(action)
            if not result.ok:
                return result
            stock = self.sandbox.inventory.get(action.target, 0) * factor
            return ToolResult(True, f"STOCK: {action.target}={stock}",
                              fault="gain",
                              classification=result.classification)
        return self._do_dispatch(action)

    def _do_dispatch(self, action: Action) -> ToolResult:
        """Run the action's handler without fault injection."""
        handler = getattr(self, f"_do_{action.tool}", None)
        if handler is None:
            return ToolResult(False, "",
                              denied_reason=f"no handler for {action.tool!r}")
        return handler(action)

    def _classification_of(self, action: Action) -> str:
        if action.tool == "file" and action.target in self.sandbox.files:
            return self.sandbox.files[action.target].classification
        return PUBLIC

    # -- file tool -----------------------------------------------------
    def _do_file(self, action: Action) -> ToolResult:
        files = self.sandbox.files
        if action.op == "read":
            entry = files.get(action.target)
            if entry is None:
                return ToolResult(False, "", denied_reason="file not found")
            return ToolResult(True, entry.content, classification=entry.classification)
        if action.op == "list":
            names = sorted(p for p in files if p.startswith(action.target))
            return ToolResult(True, "\n".join(names))
        if action.op == "write":
            content = str(action.args.get("content", ""))
            files[action.target] = FileEntry(content=content,
                                             classification=PUBLIC)
            return ToolResult(True, f"wrote {action.target}")
        if action.op == "delete":
            if action.target not in files:
                return ToolResult(False, "", denied_reason="file not found")
            del files[action.target]
            return ToolResult(True, f"deleted {action.target}")
        return ToolResult(False, "", denied_reason=f"unknown file op {action.op!r}")

    # -- web tool ------------------------------------------------------
    def _do_web(self, action: Action) -> ToolResult:
        if action.op != "fetch":
            return ToolResult(False, "", denied_reason=f"unknown web op {action.op!r}")
        body = self.sandbox.pages.get(action.target)
        if body is None:
            return ToolResult(False, "", denied_reason="page not found")
        return ToolResult(True, body)

    # -- key-value tool ------------------------------------------------
    def _do_kv(self, action: Action) -> ToolResult:
        kv = self.sandbox.kv
        if action.op == "get":
            if action.target not in kv:
                return ToolResult(False, "", denied_reason="key not found")
            return ToolResult(True, kv[action.target])
        if action.op == "put":
            kv[action.target] = str(action.args.get("value", ""))
            return ToolResult(True, f"stored {action.target}")
        if action.op == "delete":
            if action.target not in kv:
                return ToolResult(False, "", denied_reason="key not found")
            del kv[action.target]
            return ToolResult(True, f"deleted {action.target}")
        return ToolResult(False, "", denied_reason=f"unknown kv op {action.op!r}")

    # -- shell tool (simulated, never executes) ------------------------
    def _do_shell(self, action: Action) -> ToolResult:
        if action.op != "run":
            return ToolResult(False, "", denied_reason=f"unknown shell op {action.op!r}")
        command = str(action.args.get("command", "")).strip()
        name = command.split()[0] if command.split() else ""
        if name not in SHELL_ALLOWLIST:
            return ToolResult(False, "",
                              denied_reason=f"command {name!r} not allowlisted")
        if name == "echo":
            return ToolResult(True, command[len("echo"):].strip())
        if name == "date":
            return ToolResult(True, "2026-11-24")
        if name == "pwd":
            return ToolResult(True, "/workspace")
        if name == "whoami":
            return ToolResult(True, "agent")
        if name == "ls":
            return ToolResult(True, "\n".join(sorted(self.sandbox.files)))
        return ToolResult(False, "", denied_reason="unhandled command")

    # -- ledger tool ---------------------------------------------------
    def _do_ledger(self, action: Action) -> ToolResult:
        ledger = self.sandbox.ledger
        if action.op == "balance":
            balance = ledger.get(action.target, 0)
            return ToolResult(True, f"BALANCE: {action.target}={balance}")
        if action.op == "transfer":
            source = str(action.args.get("from", ""))
            dest = action.target
            try:
                amount = int(action.args.get("amount", 0))
            except (TypeError, ValueError):
                return ToolResult(False, "", denied_reason="invalid amount")
            if amount <= 0:
                return ToolResult(False, "", denied_reason="amount must be positive")
            if source not in ledger or dest not in ledger:
                return ToolResult(False, "", denied_reason="unknown account")
            if ledger[source] < amount:
                return ToolResult(False, "", denied_reason="insufficient funds")
            ledger[source] -= amount
            ledger[dest] += amount
            return ToolResult(
                True,
                f"transferred {amount} from {source} to {dest}; "
                f"BALANCE: {dest}={ledger[dest]}")
        return ToolResult(False, "", denied_reason=f"unknown ledger op {action.op!r}")

    # -- inventory tool ------------------------------------------------
    def _do_inventory(self, action: Action) -> ToolResult:
        stock = self.sandbox.inventory
        item = action.target
        if action.op == "get":
            return ToolResult(True, f"STOCK: {item}={stock.get(item, 0)}")
        if item not in stock:
            return ToolResult(False, "", denied_reason="unknown item")
        try:
            qty = int(action.args.get("qty", 1))
        except (TypeError, ValueError):
            return ToolResult(False, "", denied_reason="invalid qty")
        if qty <= 0:
            return ToolResult(False, "", denied_reason="qty must be positive")
        if action.op == "reserve":
            if stock[item] < qty:
                return ToolResult(False, "", denied_reason="insufficient stock")
            stock[item] -= qty
            self.sandbox.reservations.append({"item": item, "qty": qty})
            return ToolResult(True, f"reserved {qty} x {item}; STOCK: {item}={stock[item]}")
        if action.op == "release":
            held = sum(r["qty"] for r in self.sandbox.reservations
                       if r["item"] == item)
            if held < qty:
                return ToolResult(False, "",
                                  denied_reason="nothing reserved to release")
            remaining = qty
            kept = []
            for reservation in self.sandbox.reservations:
                if reservation["item"] == item and remaining > 0:
                    take = min(reservation["qty"], remaining)
                    reservation["qty"] -= take
                    remaining -= take
                    if reservation["qty"]:
                        kept.append(reservation)
                else:
                    kept.append(reservation)
            self.sandbox.reservations = kept
            stock[item] += qty
            return ToolResult(True, f"released {qty} x {item}; STOCK: {item}={stock[item]}")
        if action.op == "order":
            if stock[item] < qty:
                return ToolResult(False, "", denied_reason="insufficient stock")
            stock[item] -= qty
            self.sandbox._order_counter += 1
            order = {"item": item, "qty": qty,
                     "order_id": f"ord-{self.sandbox._order_counter}"}
            self.sandbox.orders.append(order)
            return ToolResult(True,
                              f"ordered {qty} x {item} ({order['order_id']}); "
                              f"STOCK: {item}={stock[item]}")
        return ToolResult(False, "", denied_reason=f"unknown inventory op {action.op!r}")
