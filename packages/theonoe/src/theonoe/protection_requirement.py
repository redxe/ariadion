from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite

from ariadion_core import canonical_json

from .bare_reliability import (
    BARE_RELIABILITY_ABS_TOLERANCE,
    BareReliabilityGoalVerdict,
    BareReliabilityReport,
    BareReliabilityStatus,
)

PROTECTION_REQUIREMENT_SCHEMA_VERSION = 1


class ProtectionNeedVerdict(str, Enum):
    NO_PROTECTION_REQUIRED = "no_protection_required"
    PROTECTION_REQUIRED = "protection_required"
    NOT_ASSESSED = "not_assessed"


@dataclass(frozen=True, slots=True)
class ProtectionRequirementMetrics:
    signed_failure_excess: float
    required_failure_reduction: float
    relative_failure_excess: float
    required_failure_suppression: float | None

    def __post_init__(self) -> None:
        _validate_numeric_scalar(self.signed_failure_excess, label="signed_failure_excess")
        _validate_numeric_scalar(self.required_failure_reduction, label="required_failure_reduction")
        _validate_numeric_scalar(self.relative_failure_excess, label="relative_failure_excess")
        if self.required_failure_suppression is not None:
            _validate_numeric_scalar(
                self.required_failure_suppression,
                label="required_failure_suppression",
            )
            if self.required_failure_suppression <= 0.0:
                raise ValueError("required_failure_suppression must be positive")

    def to_dict(self) -> dict[str, object]:
        return {
            "signed_failure_excess": self.signed_failure_excess,
            "required_failure_reduction": self.required_failure_reduction,
            "relative_failure_excess": self.relative_failure_excess,
            "required_failure_suppression": self.required_failure_suppression,
        }


@dataclass(frozen=True, slots=True)
class ProtectionRequirementReport:
    schema_version: int
    status: BareReliabilityStatus
    need_verdict: ProtectionNeedVerdict
    metrics: ProtectionRequirementMetrics | None
    supporting_bare_reliability: BareReliabilityReport
    assumptions: tuple[str, ...]
    limitations: tuple[str, ...]
    status_reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema_version != PROTECTION_REQUIREMENT_SCHEMA_VERSION:
            raise ValueError("protection requirement schema_version must match supported schema")
        if not isinstance(self.status, BareReliabilityStatus):
            raise ValueError("protection requirement status must be BareReliabilityStatus")
        if not isinstance(self.need_verdict, ProtectionNeedVerdict):
            raise ValueError("protection requirement need_verdict must be ProtectionNeedVerdict")
        if not isinstance(self.supporting_bare_reliability, BareReliabilityReport):
            raise ValueError(
                "protection requirement supporting_bare_reliability must be BareReliabilityReport"
            )
        if self.status is not self.supporting_bare_reliability.status:
            raise ValueError("protection requirement status must match supporting bare reliability status")
        if not isinstance(self.metrics, ProtectionRequirementMetrics) and self.metrics is not None:
            raise ValueError("protection requirement metrics must be ProtectionRequirementMetrics or None")
        _require_string_tuple(self.assumptions, label="protection requirement assumptions")
        _require_string_tuple(self.limitations, label="protection requirement limitations")
        _require_string_tuple(self.status_reasons, label="protection requirement status_reasons")

        expected_need_verdict = _map_need_verdict(self.supporting_bare_reliability)
        if self.need_verdict is not expected_need_verdict:
            raise ValueError("protection requirement need_verdict must match supporting bare reliability verdict")

        if self.status is BareReliabilityStatus.SUPPORTED:
            if self.metrics is None:
                raise ValueError("supported protection requirement reports require metrics")
            expected_metrics = _derive_metrics(self.supporting_bare_reliability)
            _assert_metrics_match(self.metrics, expected_metrics)
            if self.metrics.required_failure_reduction != 0.0:
                if self.need_verdict is not ProtectionNeedVerdict.PROTECTION_REQUIRED:
                    raise ValueError("non-protection reports must have zero required reduction")
            elif self.metrics.required_failure_suppression is not None:
                raise ValueError("non-protection reports must not carry suppression")
            if self.need_verdict is ProtectionNeedVerdict.PROTECTION_REQUIRED:
                if self.metrics.required_failure_reduction <= 0.0:
                    raise ValueError("protection-required reports must have positive required reduction")
                if self.metrics.required_failure_suppression is None or self.metrics.required_failure_suppression <= 1.0:
                    raise ValueError("protection-required reports must carry suppression > 1")
        else:
            if self.metrics is not None:
                raise ValueError("non-supported protection requirement reports cannot carry metrics")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "status": self.status.value,
            "need_verdict": self.need_verdict.value,
            "metrics": self.metrics.to_dict() if self.metrics is not None else None,
            "supporting_bare_reliability": self.supporting_bare_reliability.to_dict(),
            "assumptions": list(self.assumptions),
            "limitations": list(self.limitations),
            "status_reasons": list(self.status_reasons),
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


def build_protection_requirement_report(
    bare_reliability: BareReliabilityReport,
) -> ProtectionRequirementReport:
    if not isinstance(bare_reliability, BareReliabilityReport):
        raise ValueError("build_protection_requirement_report requires BareReliabilityReport")

    metrics = None
    if bare_reliability.status is BareReliabilityStatus.SUPPORTED:
        metrics = _derive_metrics(bare_reliability)

    return ProtectionRequirementReport(
        schema_version=PROTECTION_REQUIREMENT_SCHEMA_VERSION,
        status=bare_reliability.status,
        need_verdict=_map_need_verdict(bare_reliability),
        metrics=metrics,
        supporting_bare_reliability=bare_reliability,
        assumptions=bare_reliability.assumptions,
        limitations=bare_reliability.limitations,
        status_reasons=bare_reliability.status_reasons,
    )


def _derive_metrics(bare_reliability: BareReliabilityReport) -> ProtectionRequirementMetrics:
    q_bare = bare_reliability.model_relative_failure_probability
    q_goal = bare_reliability.goal.maximum_failure_probability
    if q_bare is None:
        raise ValueError("bare reliability report must expose a model-relative failure probability")
    signed_failure_excess = q_bare - q_goal
    relative_failure_excess = signed_failure_excess / q_goal
    if bare_reliability.goal_verdict is BareReliabilityGoalVerdict.VIOLATED:
        required_failure_reduction = signed_failure_excess
        required_failure_suppression = q_bare / q_goal
    else:
        required_failure_reduction = 0.0
        required_failure_suppression = None
    return ProtectionRequirementMetrics(
        signed_failure_excess=signed_failure_excess,
        required_failure_reduction=required_failure_reduction,
        relative_failure_excess=relative_failure_excess,
        required_failure_suppression=required_failure_suppression,
    )


def _map_need_verdict(bare_reliability: BareReliabilityReport) -> ProtectionNeedVerdict:
    if bare_reliability.status is not BareReliabilityStatus.SUPPORTED:
        return ProtectionNeedVerdict.NOT_ASSESSED
    if bare_reliability.goal_verdict is BareReliabilityGoalVerdict.VIOLATED:
        return ProtectionNeedVerdict.PROTECTION_REQUIRED
    return ProtectionNeedVerdict.NO_PROTECTION_REQUIRED


def _assert_metrics_match(actual: ProtectionRequirementMetrics, expected: ProtectionRequirementMetrics) -> None:
    for field_name in (
        "signed_failure_excess",
        "required_failure_reduction",
        "relative_failure_excess",
    ):
        actual_value = getattr(actual, field_name)
        expected_value = getattr(expected, field_name)
        if abs(actual_value - expected_value) > BARE_RELIABILITY_ABS_TOLERANCE:
            raise ValueError(f"protection requirement {field_name} must match nested bare reliability evidence")
    if actual.required_failure_suppression is None:
        if expected.required_failure_suppression is not None:
            raise ValueError("protection requirement suppression must match nested bare reliability evidence")
    elif expected.required_failure_suppression is None:
        raise ValueError("protection requirement suppression must match nested bare reliability evidence")
    elif abs(actual.required_failure_suppression - expected.required_failure_suppression) > BARE_RELIABILITY_ABS_TOLERANCE:
        raise ValueError("protection requirement suppression must match nested bare reliability evidence")


def _require_string_tuple(value: object, *, label: str) -> None:
    if not isinstance(value, tuple):
        raise ValueError(f"{label} must be a tuple")
    if not all(isinstance(entry, str) and entry for entry in value):
        raise ValueError(f"{label} must contain non-empty strings")


def _validate_numeric_scalar(value: object, *, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be numeric")
    numeric = float(value)
    if not isfinite(numeric):
        raise ValueError(f"{label} must be finite")


__all__ = [
    "PROTECTION_REQUIREMENT_SCHEMA_VERSION",
    "ProtectionNeedVerdict",
    "ProtectionRequirementMetrics",
    "ProtectionRequirementReport",
    "build_protection_requirement_report",
]
