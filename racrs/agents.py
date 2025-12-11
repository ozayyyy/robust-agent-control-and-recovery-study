"""Simulated agents: four recovery strategies.

Mirrors ``arsb.agents``: the same ``AgentAdapter`` interface
(``plan_legitimate`` / ``plan_after_observation``), the same
``AgentConfig`` fields (``hierarchy_filter``, ``tool_enforcement``,
``approval_mode``), ARSB's extensions (``cautious``, ``max_retries``,
``verify_before_retry``, ``should_refuse``, ``should_retry`` with
the same defaults) and the same seeded choice between readings of
an ambiguous task. Agents are deterministic decision policies, not
language models; the framework measures the architecture, not any
model.

RACRS adds four recovery strategies as configurations, and three
backwards-compatible extensions (see ``docs/architecture.md`` and
``docs/strategies.md``):

- ``AgentConfig.verify_postconditions``: check each plan step's
  postcondition (read the stated target, require the expected
  content) before accepting the step as done.
- ``AgentConfig.use_idempotency``: attach a deterministic
  idempotency key to consequential actions, so the tool layer
  executes each one at most once per run.
- ``AgentConfig.action_budget`` / ``abort_on_failure`` /
  ``rollback_on_failure``: stop the plan when the tool-call budget
  is spent, stop the plan when a step fails, and run the completed
  steps' compensations on abort.
- ``AgentAdapter.compensation_for(action, scenario)`` and
  ``AgentAdapter.idempotency_key(action, scenario)``: new methods
  the runner consults. The defaults return no compensation and no
  key, which is exactly the 7/8 behaviour.

Which 7/8 mechanism each strategy reuses is stated in
``docs/strategies.md``. In short: retry-only reuses ARSB's bounded
retry; state-aware reuses ARSB's verify-before-retry plus 7's
approval gate in spirit (it never re-executes a completed action);
policy-constrained reuses 7's tool-side enforcement and approval
gate outright, plus ARSB's verification.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, replace

from .permissions import CONSEQUENTIAL_OPS, Action, ApprovalGate
from .scenario import CONFLICT_PRIORITY, Scenario

# Faults a retry can plausibly fix. "unavailable" is not in the
# list: retrying a tool that reports itself unavailable is wasted
# work. "duplicate" is deliberately in the retry-only list and out
# of the state-aware list: that is the duplicate-action failure.
RETRYABLE_FAULTS = ("timeout", "malformed", "postcondition-failed")
RETRY_ONLY_FAULTS = ("timeout", "malformed", "duplicate")


@dataclass(frozen=True)
class AgentConfig:
    """One agent configuration under test."""

    name: str
    hierarchy_filter: bool  # ignore instructions in untrusted content
    tool_enforcement: bool  # enforce scope at the tool boundary
    approval_mode: str      # "auto" (model decides) or "gate" (user approves)
    # ARSB extensions; defaults reproduce the 7/8 behaviour.
    cautious: bool = False  # refuse ambiguous / conflicting / disallowed tasks
    max_retries: int = 0    # bounded retries after a tool fault
    verify_before_retry: bool = False  # do not retry an action that completed
    # RACRS extensions; defaults reproduce the 7/8 behaviour.
    verify_postconditions: bool = False  # check each step's postcondition
    use_idempotency: bool = False  # attach idempotency keys to effects
    action_budget: int = 0  # max tool calls per run, 0 = unlimited
    abort_on_failure: bool = False  # stop the plan when a step fails
    rollback_on_failure: bool = False  # run compensations on abort

    def approval_gate(self, scenario: Scenario) -> ApprovalGate:
        return ApprovalGate(mode=self.approval_mode,
                            preapproved=tuple(scenario.preapproved),
                            confirmation_threshold=scenario.confirmation_threshold
                            or None)


# The four recovery strategies compared by the study.
BASELINE = AgentConfig(name="baseline", hierarchy_filter=True,
                       tool_enforcement=False, approval_mode="auto",
                       max_retries=0)
RETRY_ONLY = AgentConfig(name="retry-only", hierarchy_filter=True,
                         tool_enforcement=False, approval_mode="auto",
                         max_retries=2)
STATE_AWARE = AgentConfig(name="state-aware", hierarchy_filter=True,
                          tool_enforcement=False, approval_mode="auto",
                          max_retries=2, verify_before_retry=True,
                          verify_postconditions=True, use_idempotency=True,
                          abort_on_failure=True, rollback_on_failure=True)
POLICY_CONSTRAINED = AgentConfig(
    name="policy-constrained", hierarchy_filter=True,
    tool_enforcement=True, approval_mode="gate",
    max_retries=2, verify_before_retry=True,
    verify_postconditions=True, use_idempotency=True,
    action_budget=12, abort_on_failure=True, rollback_on_failure=True)

CONFIGS = (BASELINE, RETRY_ONLY, STATE_AWARE, POLICY_CONSTRAINED)

CONFIG_BY_NAME = {c.name: c for c in CONFIGS}


class AgentAdapter:
    """Interface every agent (simulated or model-backed) implements.

    ``plan_legitimate`` returns the steps the agent takes to carry out
    the user's task. ``plan_after_observation`` returns the steps it
    takes after seeing tool outputs — this is where a stale or
    contradictory observation can mislead a weak agent into
    repeating a completed action. ``should_refuse`` and
    ``should_retry`` are the ARSB extensions; the defaults never
    refuse and never retry, which is exactly the 7/8 behaviour.
    ``compensation_for`` and ``idempotency_key`` are the RACRS
    extensions; the defaults return nothing.
    """

    def __init__(self, config: AgentConfig, seed: int = 0):
        self.config = config
        self.seed = seed

    @property
    def name(self) -> str:
        return self.config.name

    def plan_legitimate(self, scenario: Scenario) -> list[Action]:
        raise NotImplementedError

    def plan_after_observation(self, scenario: Scenario,
                               observations: list[str]) -> list[Action]:
        raise NotImplementedError

    def should_refuse(self, scenario: Scenario) -> bool:
        """Whether the agent declines the task before acting."""
        return False

    def should_retry(self, action: Action, fault: str,
                     already_completed: bool, attempt: int) -> bool:
        """Whether the agent retries an action that failed (or
        reported an error after completing). ``attempt`` is the number
        of attempts already made."""
        return False

    def compensation_for(self, action: Action,
                         scenario: Scenario) -> list[Action]:
        """Actions that undo ``action``, from the scenario's plan."""
        return []

    def idempotency_key(self, action: Action,
                        scenario: Scenario) -> str | None:
        """Deterministic key for an effectful action, or None."""
        return None


class SimulatedAgent(AgentAdapter):
    """Deterministic stand-in for a tool-using model.

    How each strategy resolves the study's situations:

    - Ambiguous tasks (``readings`` / ``candidates``): baseline
      picks a reading at random, seeded per scenario; the others
      take the first (most likely) reading. (ARSB behaviour.)
    - Conflicting instructions: baseline follows the *last*
      instruction it saw; the others follow the highest-priority
      source (system > developer > user > tool). (ARSB behaviour.)
    - Tool faults: baseline never retries; retry-only retries
      timeouts, malformed responses and duplicate error reports
      (which is how it executes a completed action twice);
      state-aware and policy-constrained retry timeouts and
      malformed responses only when the action did not complete,
      and never retry an unavailable tool.
    - Postconditions: only state-aware and policy-constrained
      check them. A failed postcondition is a retryable failure for
      those two; the others accept whatever the tool returned, so a
      stale, incomplete or contradictory observation stands.
    - Observations: follow-up rules in the scenario
      (``observation_followups``) are followed by every strategy
      from the observation it was given. For the verifying
      strategies the runner only hands over the observation that
      passed the postcondition check (a retried read), so a stale
      or contradictory value never reaches the follow-up decision.
    - Idempotency: state-aware and policy-constrained attach a
      deterministic key (``scenario-id:action-key``) to every
      consequential action, so the tool layer executes it at most
      once even if it is somehow attempted again.
    - Failure: state-aware and policy-constrained stop the plan
      when a step fails and run the completed steps' compensations;
      baseline and retry-only carry on with the remaining steps.
    """

    def _seeded_choice(self, scenario: Scenario, options: list) -> int:
        rng = random.Random(f"{self.seed}:{scenario.id}")
        return rng.randrange(len(options))

    def should_refuse(self, scenario: Scenario) -> bool:
        if not self.config.cautious:
            return False
        return scenario.category in (
            "ambiguous", "conflicting", "refusal",
            "incomplete-information")

    def should_retry(self, action: Action, fault: str,
                     already_completed: bool, attempt: int) -> bool:
        if attempt >= self.config.max_retries:
            return False
        if already_completed and self.config.verify_before_retry:
            # The action completed; an error-looking response does not
            # justify executing it again.
            return False
        if self.config.name == "retry-only":
            return fault in RETRY_ONLY_FAULTS
        if self.config.name in ("state-aware", "policy-constrained"):
            return fault in RETRYABLE_FAULTS
        return False

    def compensation_for(self, action: Action,
                         scenario: Scenario) -> list[Action]:
        step = scenario.plan_step_for(action)
        if step is None:
            return []
        return list(step.compensate)

    def idempotency_key(self, action: Action,
                        scenario: Scenario) -> str | None:
        if not self.config.use_idempotency:
            return None
        if action.op not in CONSEQUENTIAL_OPS:
            return None
        return f"{scenario.id}:{action.key()}"

    def _with_idempotency(self, scenario: Scenario,
                          actions: list[Action]) -> list[Action]:
        out = []
        for action in actions:
            key = self.idempotency_key(action, scenario)
            if key is not None and "idempotency_key" not in action.args:
                out.append(replace(action, args={**action.args,
                                                 "idempotency_key": key}))
            else:
                out.append(action)
        return out

    def plan_legitimate(self, scenario: Scenario) -> list[Action]:
        if self.config.cautious and scenario.category in (
                "ambiguous", "conflicting", "refusal",
                "incomplete-information"):
            return []
        # Ambiguous or incomplete tasks: several plausible readings.
        options = scenario.readings or scenario.candidates
        if options:
            if self.config.name == "baseline":
                return self._with_idempotency(
                    scenario, list(options[self._seeded_choice(scenario, options)]))
            return self._with_idempotency(scenario, list(options[0]))
        # Conflicting instructions from different sources.
        if scenario.conflict_instructions:
            if self.config.name == "baseline":
                return self._with_idempotency(
                    scenario, list(scenario.conflict_instructions[-1][1]))
            best = min(scenario.conflict_instructions,
                       key=lambda item: CONFLICT_PRIORITY[item[0]])
            return self._with_idempotency(scenario, list(best[1]))
        steps = list(scenario.legitimate_steps)
        if scenario.variant_distractors and self.config.name == "baseline":
            # Follows suggestions from irrelevant context.
            steps = steps + list(scenario.variant_distractors)
        return self._with_idempotency(scenario, steps)

    def plan_after_observation(self, scenario: Scenario,
                               observations: list[str]) -> list[Action]:
        follow_ups: list[Action] = []
        # Untrusted content: same hierarchy rule as 7/8.
        if scenario.injected_steps:
            if self.config.hierarchy_filter:
                if scenario.untrusted_source == "user":
                    follow_ups += list(scenario.injected_steps)
            else:
                follow_ups += list(scenario.injected_steps)
        # Observation-driven follow-ups: an agent that takes an
        # observation at face value acts on it; the verifying
        # strategies only ever receive observations that passed
        # their postcondition check, because the runner retries a
        # failed check and hands over the corrected observation.
        for rule in scenario.observation_followups:
            trigger = rule["if_observation_contains"]
            if any(trigger in obs for obs in observations):
                follow_ups += list(rule["actions"])
        return self._with_idempotency(scenario, follow_ups)
