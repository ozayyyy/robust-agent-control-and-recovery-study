"""Robust Agent Control and Recovery Study (RACRS).

Study of how tool-using AI agents behave when their plans are
interrupted by unreliable tools, changing state, partial failures,
conflicting observations or unexpected side effects. Builds on the
AI Agent Security Evaluation Framework (AASEF, project 7) and the
Agent Reliability and Safety Benchmark (ARSB, project 8): the same
scenario schema, agent adapter interface, permission model and
trace format, with a fault schedule, multi-step plans with
postconditions and compensations, four recovery strategies
(baseline, retry-only, state-aware, policy-constrained) and
recovery metrics that distinguish a successful recovery from
merely continuing execution. Agents are deterministic simulated
decision policies; tools are sandboxed in-process with synthetic
data.
"""

from .agents import (BASELINE, CONFIGS, POLICY_CONSTRAINED, RETRY_ONLY,
                     STATE_AWARE)
from .permissions import Action, ApprovalGate, Scope
from .runner import run_all, run_scenario
from .scenario import Scenario
from .trace import Trace

__version__ = "0.1.0"

__all__ = [
    "Action", "ApprovalGate", "Scope", "Scenario", "Trace",
    "BASELINE", "RETRY_ONLY", "STATE_AWARE", "POLICY_CONSTRAINED",
    "CONFIGS", "run_scenario", "run_all",
]
