"""ARSB published results, for the comparison table.

These numbers are taken from ``arsb``'s ``docs/evaluation.md``:
37 scenarios (version 1.0) x 4 configurations x seeds 0, 1, 2,
444 runs. They are reference data, not measured by this project —
the comparison table in the report labels them as such. RACRS's
own numbers are measured by ``scripts/evaluate.py``.
"""

ARSB_METHOD = "37 scenarios v1.0 x 4 configs, seeds 0, 1, 2, 444 runs"

ARSB_HEADLINE = {
    "baseline": {
        "task_success_rate": 0.595,
        "unsafe_compliance_rate": 0.713,
        "recovery_rate": 0.50,
    },
    "hierarchy-aware": {
        "task_success_rate": 0.838,
        "unsafe_compliance_rate": 0.172,
        "recovery_rate": 0.75,
    },
    "tool-side-enforced": {
        "task_success_rate": 0.811,
        "unsafe_compliance_rate": 0.0,
        "recovery_rate": 0.75,
    },
    "cautious": {
        "task_success_rate": 0.432,
        "unsafe_compliance_rate": 0.0,
        "recovery_rate": 0.75,
    },
}

# ARSB recovery rate on its tool-error-recovery category, per
# configuration. RACRS's recovery success rate is the same quantity
# (task completed after a fault, no duplicates), measured over many
# more fault classes.
ARSB_RECOVERY_BY_CONFIG = {
    "baseline": 0.50,
    "hierarchy-aware": 0.75,
    "tool-side-enforced": 0.75,
    "cautious": 0.75,
}
