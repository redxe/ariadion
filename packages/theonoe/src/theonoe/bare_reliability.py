from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from math import isfinite

from ariadion_core import ClassicalBitId, ProgramId, canonical_json, require_nonempty_identifier
from ariadion_noise import NoiseFeature
from ariadion_semantics import ClassicalAcceptanceCriterion, ReliabilityGoal

from .noise_impact import NoiseImpactReport

BARE_RELIABILITY_SCHEMA_VERSION = 1
BARE_RELIABILITY_ABS_TOLERANCE = 1e-12


class BareReliabilityMethod(str, Enum):
    EXACT_MODEL_RELATIVE_ACCEPTANCE_FAILURE_PROBABILITY = (
        "exact_model_relative_acceptance_failure_probability"
    )


class BareReliabilityDistributionKind(str, Enum):
    PHYSICAL_OUTPUT = "physical_output"
    REPORTED_OUTPUT = "reported_output"


class BareReliabilityBitOrder(str, Enum):
    TARGETS_LSB_FIRST = "targets_lsb_first"


class BareReliabilityProbabilityScope(str, Enum):
    JOINT_RETURN = "joint_return"


class BareReliabilityStatus(str, Enum):
    SUPPORTED = "supported"
    INCOMPLETE_MODEL = "incomplete_model"
    INDETERMINATE = "indeterminate"
    UNSUPPORTED = "unsupported"


class BareReliabilityGoalVerdict(str, Enum):
    SATISFIED = "satisfied"
    VIOLATED = "violated"
    NOT_EVALUATED = "not_evaluated"


class BareReliabilityCompletenessIssue(str, Enum):
    COVERAGE_SNAPSHOT_ABSENT = "coverage_snapshot_absent"
    IDEAL_ONLY_TWO_QUBIT_OPERATION_PRESENT = "ideal_only_two_qubit_operation_present"
    UNSUPPORTED_FEATURES_PRESENT = "unsupported_features_present"


@dataclass(frozen=True, slots=True)
class BoundClassicalAcceptanceCriterion:
    circuit_id: ProgramId
    result_ids: tuple[ClassicalBitId, ...]
    bit_order: BareReliabilityBitOrder = BareReliabilityBitOrder.TARGETS_LSB_FIRST
    scope: BareReliabilityProbabilityScope = BareReliabilityProbabilityScope.JOINT_RETURN
    distribution_kind: BareReliabilityDistributionKind = BareReliabilityDistributionKind.PHYSICAL_OUTPUT
    accepted_outcomes: tuple[tuple[int, ...], ...] = ()
    accepted_indices: tuple[int, ...] = field(init=False)

    def __post_init__(self) -> None:
        require_nonempty_identifier(self.circuit_id, label="bare reliability bound circuit ID")
        if not isinstance(self.result_ids, tuple) or not self.result_ids:
            raise ValueError("bare reliability bound result_ids must be a non-empty tuple")
        if len(self.result_ids) != len(set(self.result_ids)):
            raise ValueError("bare reliability bound result_ids must be unique")
        for result_id in self.result_ids:
            require_nonempty_identifier(result_id, label="bare reliability bound result ID")
        if not isinstance(self.bit_order, BareReliabilityBitOrder):
            raise ValueError("bare reliability bound bit_order must be BareReliabilityBitOrder")
        if not isinstance(self.scope, BareReliabilityProbabilityScope):
            raise ValueError("bare reliability bound scope must be BareReliabilityProbabilityScope")
        if not isinstance(self.distribution_kind, BareReliabilityDistributionKind):
            raise ValueError(
                "bare reliability bound distribution_kind must be BareReliabilityDistributionKind"
            )
        if not isinstance(self.accepted_outcomes, tuple):
            raise ValueError("bare reliability bound accepted_outcomes must be a tuple")
        canonical_outcomes: list[tuple[int, ...]] = []
        accepted_indices: list[int] = []
        seen_outcomes: set[tuple[int, ...]] = set()
        seen_indices: set[int] = set()
        expected_arity = len(self.result_ids)
        for outcome in self.accepted_outcomes:
            if not isinstance(outcome, tuple):
                raise ValueError("bare reliability bound accepted outcomes must be tuples")
            if len(outcome) != expected_arity:
                raise ValueError("bare reliability bound accepted outcomes must match result_ids")
            if any(isinstance(bit, bool) or not isinstance(bit, int) or bit not in {0, 1} for bit in outcome):
                raise ValueError("bare reliability bound accepted outcomes must contain only 0/1 bits")
            if outcome in seen_outcomes:
                raise ValueError("bare reliability bound accepted_outcomes must be unique")
            index = _outcome_index(outcome)
            if index in seen_indices:
                raise ValueError("bare reliability bound accepted probability indices must be unique")
            seen_outcomes.add(outcome)
            seen_indices.add(index)
            canonical_outcomes.append(outcome)
            accepted_indices.append(index)
        canonical_pairs = sorted(zip(accepted_indices, canonical_outcomes), key=lambda item: item[0])
        object.__setattr__(self, "accepted_outcomes", tuple(outcome for _, outcome in canonical_pairs))
        object.__setattr__(self, "accepted_indices", tuple(index for index, _ in canonical_pairs))

    def to_dict(self) -> dict[str, object]:
        return {
            "circuit_id": self.circuit_id,
            "result_ids": list(self.result_ids),
            "bit_order": self.bit_order.value,
            "scope": self.scope.value,
            "distribution_kind": self.distribution_kind.value,
            "accepted_outcomes": [list(outcome) for outcome in self.accepted_outcomes],
            "accepted_indices": list(self.accepted_indices),
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class BareReliabilityReport:
    schema_version: int
    method: BareReliabilityMethod
    status: BareReliabilityStatus
    goal_verdict: BareReliabilityGoalVerdict
    goal: ReliabilityGoal
    bound_acceptance: BoundClassicalAcceptanceCriterion | None
    model_relative_success_probability: float | None
    model_relative_failure_probability: float | None
    goal_margin: float | None
    supporting_noise_impact: NoiseImpactReport
    executed_noise_features: tuple[NoiseFeature, ...]
    unsupported_features: tuple[NoiseFeature, ...]
    assumptions: tuple[str, ...]
    completeness_issues: tuple[BareReliabilityCompletenessIssue, ...]
    limitations: tuple[str, ...]
    status_reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema_version != BARE_RELIABILITY_SCHEMA_VERSION:
            raise ValueError("bare reliability schema_version must match supported schema")
        if not isinstance(self.method, BareReliabilityMethod):
            raise ValueError("bare reliability method must be BareReliabilityMethod")
        if not isinstance(self.status, BareReliabilityStatus):
            raise ValueError("bare reliability status must be BareReliabilityStatus")
        if not isinstance(self.goal_verdict, BareReliabilityGoalVerdict):
            raise ValueError("bare reliability goal_verdict must be BareReliabilityGoalVerdict")
        if not isinstance(self.goal, ReliabilityGoal):
            raise ValueError("bare reliability goal must be ReliabilityGoal")
        if self.bound_acceptance is not None and not isinstance(
            self.bound_acceptance, BoundClassicalAcceptanceCriterion
        ):
            raise ValueError(
                "bare reliability bound_acceptance must be BoundClassicalAcceptanceCriterion or None"
            )
        if not isinstance(self.supporting_noise_impact, NoiseImpactReport):
            raise ValueError(
                "bare reliability supporting_noise_impact must be NoiseImpactReport"
            )
        if (
            self.bound_acceptance is not None
            and self.bound_acceptance.circuit_id
            != self.supporting_noise_impact.comparison.circuit_id
        ):
            raise ValueError(
                "bare reliability bound_acceptance circuit_id must match supporting noise impact circuit_id"
            )
        _require_noise_feature_tuple(self.executed_noise_features, label="bare reliability executed_noise_features")
        _require_noise_feature_tuple(self.unsupported_features, label="bare reliability unsupported_features")
        if len(self.unsupported_features) != len(set(self.unsupported_features)):
            raise ValueError("bare reliability unsupported_features must be unique")
        _require_string_tuple(self.assumptions, label="bare reliability assumptions")
        if not isinstance(self.completeness_issues, tuple):
            raise ValueError("bare reliability completeness_issues must be a tuple")
        if not all(isinstance(issue, BareReliabilityCompletenessIssue) for issue in self.completeness_issues):
            raise ValueError(
                "bare reliability completeness_issues must contain BareReliabilityCompletenessIssue values"
            )
        if len(self.completeness_issues) != len(set(self.completeness_issues)):
            raise ValueError("bare reliability completeness_issues must be unique")
        _require_string_tuple(self.limitations, label="bare reliability limitations")
        _require_string_tuple(self.status_reasons, label="bare reliability status_reasons")

        has_scalar_success = self.model_relative_success_probability is not None
        has_scalar_failure = self.model_relative_failure_probability is not None
        if has_scalar_success != has_scalar_failure:
            raise ValueError(
                "bare reliability scalar diagnostics require both success and failure probabilities"
            )
        has_scalar_diagnostics = has_scalar_success
        if has_scalar_diagnostics:
            assert self.model_relative_success_probability is not None
            assert self.model_relative_failure_probability is not None
            _validate_probability_scalar(
                self.model_relative_success_probability,
                label="bare reliability model_relative_success_probability",
            )
            _validate_probability_scalar(
                self.model_relative_failure_probability,
                label="bare reliability model_relative_failure_probability",
            )
            probability_total = (
                self.model_relative_success_probability
                + self.model_relative_failure_probability
            )
            if abs(probability_total - 1.0) > BARE_RELIABILITY_ABS_TOLERANCE:
                raise ValueError(
                    "bare reliability scalar diagnostics must sum to one within tolerance"
                )
        if self.status is BareReliabilityStatus.SUPPORTED:
            if self.goal.confidence is not None:
                raise ValueError("supported bare reliability reports cannot carry a confidence-bearing goal")
            if self.goal_verdict not in {
                BareReliabilityGoalVerdict.SATISFIED,
                BareReliabilityGoalVerdict.VIOLATED,
                BareReliabilityGoalVerdict.NOT_EVALUATED,
            }:
                raise ValueError("supported bare reliability reports must use a recognized verdict")
            if self.bound_acceptance is None or not has_scalar_diagnostics:
                raise ValueError("supported bare reliability reports require bound acceptance and scalar diagnostics")
            if self.completeness_issues:
                raise ValueError("supported bare reliability reports cannot carry completeness issues")
            if self.unsupported_features:
                raise ValueError("supported bare reliability reports cannot carry unsupported features")
            if self.goal_verdict is BareReliabilityGoalVerdict.NOT_EVALUATED:
                if self.goal_margin is not None:
                    raise ValueError("not-evaluated bare reliability verdict cannot carry a goal margin")
                if not self.status_reasons:
                    raise ValueError("not-evaluated bare reliability verdict requires a status reason")
            else:
                if self.goal_margin is None:
                    raise ValueError("evaluated bare reliability verdicts require a goal margin")
        elif self.status is BareReliabilityStatus.INCOMPLETE_MODEL:
            if self.goal_verdict is not BareReliabilityGoalVerdict.NOT_EVALUATED:
                raise ValueError("incomplete bare reliability reports must not claim a verdict")
            if self.goal_margin is not None:
                raise ValueError("incomplete bare reliability reports cannot carry a goal margin")
            if not self.status_reasons:
                raise ValueError("incomplete bare reliability reports require status reasons")
            if self.bound_acceptance is None and has_scalar_diagnostics:
                raise ValueError("bare reliability scalar diagnostics require a bound acceptance snapshot")
            if self.bound_acceptance is not None and not has_scalar_diagnostics:
                raise ValueError(
                    "incomplete bare reliability reports with bound acceptance require scalar diagnostics"
                )
        elif self.status is BareReliabilityStatus.INDETERMINATE:
            if self.goal_verdict is not BareReliabilityGoalVerdict.NOT_EVALUATED:
                raise ValueError("indeterminate bare reliability reports must not claim a verdict")
            if self.goal_margin is not None:
                raise ValueError("indeterminate bare reliability reports cannot carry a goal margin")
            if self.goal.confidence is None:
                raise ValueError("indeterminate bare reliability reports require a confidence-bearing goal")
            if not self.status_reasons:
                raise ValueError("indeterminate bare reliability reports require status reasons")
            if self.bound_acceptance is None and has_scalar_diagnostics:
                raise ValueError("bare reliability scalar diagnostics require a bound acceptance snapshot")
            if self.bound_acceptance is not None and not has_scalar_diagnostics:
                raise ValueError(
                    "indeterminate bare reliability reports with bound acceptance require scalar diagnostics"
                )
        else:
            if self.goal_verdict is not BareReliabilityGoalVerdict.NOT_EVALUATED:
                raise ValueError("unsupported bare reliability reports must not claim a verdict")
            if self.goal_margin is not None:
                raise ValueError("unsupported bare reliability reports cannot carry a goal margin")
            if self.bound_acceptance is not None or has_scalar_diagnostics:
                raise ValueError("unsupported bare reliability reports cannot carry assessment scalars")
            if not self.status_reasons:
                raise ValueError("unsupported bare reliability reports require status reasons")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "method": self.method.value,
            "status": self.status.value,
            "goal_verdict": self.goal_verdict.value,
            "goal": self.goal.to_dict(),
            "bound_acceptance": self.bound_acceptance.to_dict() if self.bound_acceptance is not None else None,
            "model_relative_success_probability": self.model_relative_success_probability,
            "model_relative_failure_probability": self.model_relative_failure_probability,
            "goal_margin": self.goal_margin,
            "supporting_noise_impact": self.supporting_noise_impact.to_dict(),
            "executed_noise_features": [feature.value for feature in self.executed_noise_features],
            "unsupported_features": [feature.value for feature in self.unsupported_features],
            "assumptions": list(self.assumptions),
            "completeness_issues": [issue.value for issue in self.completeness_issues],
            "limitations": list(self.limitations),
            "status_reasons": list(self.status_reasons),
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


def _outcome_index(outcome: tuple[int, ...]) -> int:
    return sum(bit << index for index, bit in enumerate(outcome))


def _require_noise_feature_tuple(value: object, *, label: str) -> None:
    if not isinstance(value, tuple):
        raise ValueError(f"{label} must be a tuple")
    if not all(isinstance(feature, NoiseFeature) for feature in value):
        raise ValueError(f"{label} must contain NoiseFeature values")


def _require_string_tuple(value: object, *, label: str) -> None:
    if not isinstance(value, tuple):
        raise ValueError(f"{label} must be a tuple")
    if not all(isinstance(entry, str) and entry for entry in value):
        raise ValueError(f"{label} must contain non-empty strings")


def _validate_probability_scalar(value: object, *, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be numeric")
    numeric = float(value)
    if not isfinite(numeric):
        raise ValueError(f"{label} must be finite")
    if numeric < 0.0 or numeric > 1.0:
        raise ValueError(f"{label} must be within [0, 1]")


__all__ = [
    "BARE_RELIABILITY_ABS_TOLERANCE",
    "BARE_RELIABILITY_SCHEMA_VERSION",
    "BareReliabilityBitOrder",
    "BareReliabilityCompletenessIssue",
    "BareReliabilityDistributionKind",
    "BareReliabilityGoalVerdict",
    "BareReliabilityMethod",
    "BareReliabilityProbabilityScope",
    "BareReliabilityReport",
    "BareReliabilityStatus",
    "BoundClassicalAcceptanceCriterion",
]