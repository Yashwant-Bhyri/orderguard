"""Frozen evaluation bench for OrderGuard System One.

The public surface is deliberately small: Case extraction, the four
renderings, the metric functions, group splits and the spec hash.
"""

from __future__ import annotations

from .baselines import CodeLogisticReader
from .cases import (
    CAUSE_TRUTH_TYPE,
    FAMILY_AXES,
    SHIFT_AXES,
    TRUTH_TYPES,
    Case,
    LabelRecord,
    axes_for_meta,
    cases,
    labels,
    reader_inputs,
    tag_shift_axes,
    truth_type_for,
)
from .metrics import (
    Metric,
    auroc,
    bootstrap_ci,
    cost_summary,
    coverage_at_false_allow,
    ece,
    escalation_rate,
    false_holds_per_1000,
    pointer_accuracy,
    risk_from_prob,
    select_calibration_threshold,
    select_conformal_threshold,
    top_cause_accuracy,
)
from .render import RENDERINGS, render_case, render_lengths
from .splits import (
    SPLIT_NAMES,
    assert_group_disjoint,
    group_split,
    split_summary,
)
from .spec import expected_hash, spec_hash, verify_spec

__all__ = [
    "CAUSE_TRUTH_TYPE",
    "FAMILY_AXES",
    "RENDERINGS",
    "SHIFT_AXES",
    "SPLIT_NAMES",
    "TRUTH_TYPES",
    "Case",
    "CodeLogisticReader",
    "LabelRecord",
    "Metric",
    "assert_group_disjoint",
    "auroc",
    "axes_for_meta",
    "bootstrap_ci",
    "cases",
    "cost_summary",
    "coverage_at_false_allow",
    "ece",
    "escalation_rate",
    "expected_hash",
    "false_holds_per_1000",
    "group_split",
    "labels",
    "pointer_accuracy",
    "reader_inputs",
    "render_case",
    "render_lengths",
    "risk_from_prob",
    "select_calibration_threshold",
    "select_conformal_threshold",
    "spec_hash",
    "split_summary",
    "tag_shift_axes",
    "top_cause_accuracy",
    "truth_type_for",
    "verify_spec",
]
