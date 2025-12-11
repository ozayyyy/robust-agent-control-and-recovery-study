"""Scenario schema.

Mirrors ``arsb.scenario.Scenario`` exactly: one JSON file per
scenario, validated on load, with the same required and optional
fields (``id``, ``version``, ``category``, ``title``, ``description``,
``user_task``, ``scope``, ``setup``, ``legitimate_steps``,
``untrusted_source``, ``untrusted_content``, ``injected_steps``,
``preapproved``, ``expected`` with ``must_complete`` /
``must_not_complete`` action keys of the form ``tool:op:target``),
plus ARSB's optional extensions (``readings``,
``conflict_instructions``, ``candidates``, ``variant_distractors``,
``tool_faults``, ``group``, ``expected_outcome``) accepted unchanged.

RACRS extends the schema in a backwards-compatible way with
optional fields only — a 7/8 scenario file loads here unchanged
(tested in ``tests/test_compat.py``):

- ``fault_schedule``: the fault schedule for this task, mapping
  action key to ``{"fault", "fail_times", "output"}``. The same
  shape as ARSB's ``tool_faults``; if both are present,
  ``fault_schedule`` wins. Faults: ARSB's ``timeout``,
  ``malformed``, ``unavailable``, ``duplicate``, plus RACRS's
  observation faults ``stale``, ``incomplete``, ``contradictory``,
  which only apply to read operations (validated on load).
- ``plan_steps``: the task's multi-step plan, a list of
  ``{"action", "postcondition", "compensate"}``. ``postcondition``
  is ``{"tool", "op", "target", "expected_contains"}``: after the
  step, the runner reads that target and checks the output
  contains the expected string. ``compensate`` is a list of actions
  that undo the step (release a reservation, refund a transfer).
  When absent, the plan is derived from ``legitimate_steps`` with
  no postconditions and no compensations.
- ``expected_final_state``: the sandbox state a correct run ends
  in, as a partial ``{"files", "kv", "ledger", "inventory",
  "orders"}`` mapping. Only the keys present are compared; an
  ``orders`` value is the expected number of orders.
- ``permitted_side_effects``: action keys that may complete in
  addition to ``must_complete`` (verification reads are reads, so
  they never count as side effects).
- ``observation_followups``: ``[{"if_observation_contains": str,
  "actions": [...]}]``. After observing tool output, an agent that
  takes an observation at face value follows the matching rule;
  an agent that verifies its observations first checks the
  postcondition, and only follows up when the verified observation
  still matches.
- ``confirmation_threshold``: amounts at or below this value are
  approved even in gate mode (see ``permissions.ApprovalGate``).
  Default 0: every consequential action needs a pre-approval in
  gate mode, as in 7/8.
- ``action_budget``: maximum tool calls for the run. Default 0:
  no budget. The policy-constrained configuration also has a
  default budget of 12; the scenario value wins when set.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .permissions import Action, Scope
from .tools import OBSERVATION_FAULTS, READ_OPS

# AASEF categories, accepted unchanged so 7 scenario files load.
AASEF_CATEGORIES = (
    "direct-injection",
    "indirect-web",
    "indirect-document",
    "indirect-tool-output",
    "unauthorised-tool",
    "privilege-boundary",
    "out-of-scope-data",
    "cross-task-leak",
    "cross-session-leak",
    "approval-bypass",
    "benign",
)

# ARSB categories, accepted unchanged so 8 scenario files load.
ARSB_CATEGORIES = (
    "ambiguous",
    "conflicting",
    "adversarial",
    "incomplete-information",
    "refusal",
    "prompt-variation",
    "tool-error-recovery",
)

# New RACRS categories: one per fault class / recovery situation.
RACRS_CATEGORIES = (
    "timeout",
    "malformed",
    "unavailable",
    "stale-observation",
    "incomplete-observation",
    "contradictory-observation",
    "duplicate-delivery",
    "partial-failure",
    "rollback",
    "confirmation",
    "multi-fault",
)

CATEGORIES = AASEF_CATEGORIES + ARSB_CATEGORIES + RACRS_CATEGORIES

UNTRUSTED_SOURCES = ("user", "web", "document", "tool-output", "none")

CONFLICT_SOURCES = ("system", "developer", "user", "tool")
CONFLICT_PRIORITY = {s: i for i, s in enumerate(CONFLICT_SOURCES)}

FAULTS = ("timeout", "malformed", "unavailable", "duplicate") + OBSERVATION_FAULTS

EXPECTED_OUTCOMES = ("complete", "refuse", "ask")


@dataclass
class PlanStep:
    """One step of the task's plan, with its check and its undo."""

    action: Action
    postcondition: dict | None = None
    compensate: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "action": self.action.to_dict(),
            "postcondition": self.postcondition,
            "compensate": [a.to_dict() for a in self.compensate],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PlanStep":
        return cls(
            action=Action.from_dict(data["action"]),
            postcondition=data.get("postcondition"),
            compensate=[Action.from_dict(a)
                        for a in data.get("compensate", [])],
        )


@dataclass
class Scenario:
    id: str
    version: str
    category: str
    title: str
    user_task: str
    scope: Scope
    setup: dict
    legitimate_steps: list
    expected: dict
    description: str = ""
    untrusted_source: str = "none"
    untrusted_content: str = ""
    injected_steps: list = field(default_factory=list)
    preapproved: list = field(default_factory=list)
    # ARSB extensions (all optional, backwards compatible).
    readings: list = field(default_factory=list)
    conflict_instructions: list = field(default_factory=list)
    candidates: list = field(default_factory=list)
    variant_distractors: list = field(default_factory=list)
    tool_faults: dict = field(default_factory=dict)
    group: str = ""
    expected_outcome: str = "complete"
    # RACRS extensions (all optional, backwards compatible).
    fault_schedule: dict = field(default_factory=dict)
    plan_steps: list = field(default_factory=list)
    expected_final_state: dict = field(default_factory=dict)
    permitted_side_effects: list = field(default_factory=list)
    observation_followups: list = field(default_factory=list)
    confirmation_threshold: int = 0
    action_budget: int = 0

    @property
    def faults(self) -> dict:
        """The fault schedule in force: RACRS's wins over ARSB's."""
        return self.fault_schedule or self.tool_faults

    def plan_step_for(self, action: Action) -> PlanStep | None:
        for step in self.plan_steps:
            if step.action.key() == action.key():
                return step
        return None

    def to_dict(self) -> dict:
        return {
            "id": self.id, "version": self.version, "category": self.category,
            "title": self.title, "description": self.description,
            "user_task": self.user_task, "scope": self.scope.to_dict(),
            "setup": self.setup,
            "legitimate_steps": [a.to_dict() for a in self.legitimate_steps],
            "untrusted_source": self.untrusted_source,
            "untrusted_content": self.untrusted_content,
            "injected_steps": [a.to_dict() for a in self.injected_steps],
            "preapproved": list(self.preapproved),
            "expected": self.expected,
            "readings": [[a.to_dict() for a in r] for r in self.readings],
            "conflict_instructions": [
                {"source": src, "actions": [a.to_dict() for a in acts]}
                for src, acts in self.conflict_instructions],
            "candidates": [[a.to_dict() for a in c] for c in self.candidates],
            "variant_distractors": [a.to_dict() for a in self.variant_distractors],
            "tool_faults": dict(self.tool_faults),
            "group": self.group,
            "expected_outcome": self.expected_outcome,
            "fault_schedule": dict(self.fault_schedule),
            "plan_steps": [s.to_dict() for s in self.plan_steps],
            "expected_final_state": self.expected_final_state,
            "permitted_side_effects": list(self.permitted_side_effects),
            "observation_followups": [
                {"if_observation_contains": r["if_observation_contains"],
                 "actions": [a.to_dict() for a in r["actions"]]}
                for r in self.observation_followups],
            "confirmation_threshold": self.confirmation_threshold,
            "action_budget": self.action_budget,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Scenario":
        category = data["category"]
        if category not in CATEGORIES:
            raise ValueError(f"unknown category {category!r} in {data.get('id')}")
        source = data.get("untrusted_source", "none")
        if source not in UNTRUSTED_SOURCES:
            raise ValueError(f"unknown untrusted_source {source!r} in {data.get('id')}")
        expected = data["expected"]
        if not isinstance(expected, dict) or "must_complete" not in expected \
                or "must_not_complete" not in expected:
            raise ValueError(f"scenario {data.get('id')} missing expected lists")
        for entry in data.get("conflict_instructions", []):
            if entry.get("source") not in CONFLICT_SOURCES:
                raise ValueError(
                    f"unknown conflict source {entry.get('source')!r} in {data.get('id')}")
        faults = data.get("fault_schedule") or data.get("tool_faults", {})
        for key, fault in faults.items():
            if fault.get("fault") not in FAULTS:
                raise ValueError(f"unknown fault {fault.get('fault')!r} in {data.get('id')}")
            if fault.get("fault") in OBSERVATION_FAULTS:
                tool, op, _target = key.split(":", 2)
                if op not in READ_OPS.get(tool, set()):
                    raise ValueError(
                        f"observation fault {fault.get('fault')!r} on non-read "
                        f"action {key!r} in {data.get('id')}")
        outcome = data.get("expected_outcome")
        if outcome is None:
            outcome = ("refuse" if category == "refusal"
                       else "ask" if category == "incomplete-information"
                       else "complete")
        if outcome not in EXPECTED_OUTCOMES:
            raise ValueError(f"unknown expected_outcome {outcome!r} in {data.get('id')}")
        return cls(
            id=data["id"], version=str(data.get("version", "1.0")),
            category=category, title=data.get("title", ""),
            description=data.get("description", ""),
            user_task=data["user_task"],
            scope=Scope.from_dict(data.get("scope", {})),
            setup=data.get("setup", {}),
            legitimate_steps=[Action.from_dict(a)
                              for a in data.get("legitimate_steps", [])],
            untrusted_source=source,
            untrusted_content=data.get("untrusted_content", ""),
            injected_steps=[Action.from_dict(a)
                            for a in data.get("injected_steps", [])],
            preapproved=list(data.get("preapproved", [])),
            expected=expected,
            readings=[[Action.from_dict(a) for a in r]
                      for r in data.get("readings", [])],
            conflict_instructions=[
                (e["source"], [Action.from_dict(a) for a in e.get("actions", [])])
                for e in data.get("conflict_instructions", [])],
            candidates=[[Action.from_dict(a) for a in c]
                        for c in data.get("candidates", [])],
            variant_distractors=[Action.from_dict(a)
                                 for a in data.get("variant_distractors", [])],
            tool_faults=dict(data.get("tool_faults", {})),
            group=data.get("group", ""),
            expected_outcome=outcome,
            fault_schedule=dict(data.get("fault_schedule", {})),
            plan_steps=[PlanStep.from_dict(s)
                        for s in data.get("plan_steps", [])],
            expected_final_state=data.get("expected_final_state", {}),
            permitted_side_effects=list(data.get("permitted_side_effects", [])),
            observation_followups=[
                {"if_observation_contains": r["if_observation_contains"],
                 "actions": [Action.from_dict(a) for a in r["actions"]]}
                for r in data.get("observation_followups", [])],
            confirmation_threshold=int(data.get("confirmation_threshold", 0)),
            action_budget=int(data.get("action_budget", 0)),
        )

    @classmethod
    def load(cls, path: Path | str) -> "Scenario":
        with open(path, encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh))

    @classmethod
    def load_all(cls, directory: Path | str) -> list["Scenario"]:
        scenarios = []
        for path in sorted(Path(directory).glob("*.json")):
            scenarios.append(cls.load(path))
        ids = [s.id for s in scenarios]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate scenario ids")
        return scenarios
