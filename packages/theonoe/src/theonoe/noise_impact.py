from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isclose, isfinite, sqrt
from typing import Final

from ariadion_core import ProgramId, canonical_json, require_nonempty_identifier
from ariadion_simulator import GateNoiseApplicationEvent, IdleDecoherenceEvent

NOISE_IMPACT_SCHEMA_VERSION: Final = 1
NOISE_IMPACT_ABS_TOLERANCE: Final = 1e-12


class MetricProvenance(str, Enum):
    OBSERVED = "observed"
    DERIVED = "derived"
    COUNTERFACTUAL = "counterfactual"


class NoiseImpactScope(str, Enum):
    STATE = "state"
    OUTPUT_DISTRIBUTION = "output_distribution"
    EVENT_EVIDENCE = "event_evidence"


class NoiseImpactEventKind(str, Enum):
    IDLE_DECOHERENCE = "idle_decoherence"
    GATE_CHANNEL = "gate_channel"
    READOUT_DISTORTION = "readout_distortion"


@dataclass(frozen=True, slots=True)
class DensityStateReport:
    qubit_count: int
    dimension: int
    computational_basis_populations: tuple[float, ...]
    purity: float
    l1_coherence: float
    basis_dependent: bool = True
    basis: str = "computational"

    def __post_init__(self) -> None:
        if isinstance(self.qubit_count, bool) or not isinstance(self.qubit_count, int) or self.qubit_count < 0:
            raise ValueError("density state report qubit_count must be a non-negative integer")
        if isinstance(self.dimension, bool) or not isinstance(self.dimension, int) or self.dimension <= 0:
            raise ValueError("density state report dimension must be a positive integer")
        if self.dimension != 1 << self.qubit_count:
            raise ValueError("density state report dimension must equal 2**qubit_count")
        if not isinstance(self.computational_basis_populations, tuple) or len(self.computational_basis_populations) != self.dimension:
            raise ValueError(
                "density state report computational_basis_populations must contain one value per basis state"
            )
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not isfinite(float(value))
            or value < -NOISE_IMPACT_ABS_TOLERANCE
            for value in self.computational_basis_populations
        ):
            raise ValueError("density state report populations must be finite non-negative values")
        if not isclose(
            sum(self.computational_basis_populations),
            1.0,
            rel_tol=0.0,
            abs_tol=NOISE_IMPACT_ABS_TOLERANCE,
        ):
            raise ValueError("density state report populations must sum to one")
        for value, label in ((self.purity, "purity"), (self.l1_coherence, "l1_coherence")):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(float(value)):
                raise ValueError(f"density state report {label} must be finite")
        if not isinstance(self.basis_dependent, bool):
            raise ValueError("density state report basis_dependent must be a boolean")
        require_nonempty_identifier(self.basis, label="density state report basis")

    def to_dict(self) -> dict[str, object]:
        return {
            "qubit_count": self.qubit_count,
            "dimension": self.dimension,
            "computational_basis_populations": list(self.computational_basis_populations),
            "purity": self.purity,
            "l1_coherence": self.l1_coherence,
            "basis_dependent": self.basis_dependent,
            "basis": self.basis,
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class NoiseImpactMetric:
    name: str
    value: float
    definition: str
    tolerance: float
    provenance: MetricProvenance
    scope: NoiseImpactScope
    basis_dependent: bool = False
    basis: str | None = None

    def __post_init__(self) -> None:
        require_nonempty_identifier(self.name, label="noise impact metric name")
        if isinstance(self.value, bool) or not isinstance(self.value, (int, float)) or not isfinite(float(self.value)):
            raise ValueError("noise impact metric value must be finite")
        require_nonempty_identifier(self.definition, label="noise impact metric definition")
        if isinstance(self.tolerance, bool) or not isinstance(self.tolerance, (int, float)) or not isfinite(float(self.tolerance)) or self.tolerance < 0:
            raise ValueError("noise impact metric tolerance must be finite and non-negative")
        if not isinstance(self.provenance, MetricProvenance):
            raise ValueError("noise impact metric provenance must be MetricProvenance")
        if not isinstance(self.scope, NoiseImpactScope):
            raise ValueError("noise impact metric scope must be NoiseImpactScope")
        if not isinstance(self.basis_dependent, bool):
            raise ValueError("noise impact metric basis_dependent must be a boolean")
        if self.basis is not None:
            require_nonempty_identifier(self.basis, label="noise impact metric basis")

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "value": self.value,
            "definition": self.definition,
            "tolerance": self.tolerance,
            "provenance": self.provenance.value,
            "scope": self.scope.value,
            "basis_dependent": self.basis_dependent,
            "basis": self.basis,
        }


@dataclass(frozen=True, slots=True)
class NoiseImpactComparisonProvenance:
    circuit_id: ProgramId
    representation: str
    backend_id: str
    ideal_baseline_derivation: str
    metric_tolerance: float = NOISE_IMPACT_ABS_TOLERANCE

    def __post_init__(self) -> None:
        require_nonempty_identifier(self.circuit_id, label="noise impact circuit ID")
        require_nonempty_identifier(self.representation, label="noise impact representation")
        require_nonempty_identifier(self.backend_id, label="noise impact backend ID")
        require_nonempty_identifier(
            self.ideal_baseline_derivation,
            label="noise impact ideal baseline derivation",
        )
        if (
            isinstance(self.metric_tolerance, bool)
            or not isinstance(self.metric_tolerance, (int, float))
            or not isfinite(float(self.metric_tolerance))
            or self.metric_tolerance < 0
        ):
            raise ValueError("noise impact metric_tolerance must be finite and non-negative")

    def to_dict(self) -> dict[str, object]:
        return {
            "circuit_id": self.circuit_id,
            "representation": self.representation,
            "backend_id": self.backend_id,
            "ideal_baseline_derivation": self.ideal_baseline_derivation,
            "metric_tolerance": self.metric_tolerance,
        }


@dataclass(frozen=True, slots=True)
class IdleNoiseImpactEvidence:
    slot: int
    start_ns: float
    end_ns: float
    duration_ns: float
    gamma1: float
    p_phi: float
    mode: str
    t1_ns: float | None
    t2_ns: float | None
    tphi_inverse_per_ns: float | None

    def to_dict(self) -> dict[str, object]:
        return {
            "slot": self.slot,
            "start_ns": self.start_ns,
            "end_ns": self.end_ns,
            "duration_ns": self.duration_ns,
            "gamma1": self.gamma1,
            "p_phi": self.p_phi,
            "mode": self.mode,
            "t1_ns": self.t1_ns,
            "t2_ns": self.t2_ns,
            "tphi_inverse_per_ns": self.tphi_inverse_per_ns,
        }


@dataclass(frozen=True, slots=True)
class GateNoiseImpactEvidence:
    operation_id: str
    target_slot: int
    gate: str
    channel: dict[str, object]
    application_order: int
    application_ordering: str

    def to_dict(self) -> dict[str, object]:
        return {
            "operation_id": self.operation_id,
            "target_slot": self.target_slot,
            "gate": self.gate,
            "channel": self.channel,
            "application_order": self.application_order,
            "application_ordering": self.application_ordering,
        }


@dataclass(frozen=True, slots=True)
class ReadoutDistortionEvidence:
    channel: dict[str, object]
    physical_vs_reported_tvd: float

    def to_dict(self) -> dict[str, object]:
        return {
            "channel": self.channel,
            "physical_vs_reported_tvd": self.physical_vs_reported_tvd,
        }


@dataclass(frozen=True, slots=True)
class NoiseImpactEventFinding:
    kind: NoiseImpactEventKind
    provenance: MetricProvenance
    summary: str
    idle: IdleNoiseImpactEvidence | None = None
    gate: GateNoiseImpactEvidence | None = None
    readout: ReadoutDistortionEvidence | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, NoiseImpactEventKind):
            raise ValueError("noise impact finding kind must be NoiseImpactEventKind")
        if not isinstance(self.provenance, MetricProvenance):
            raise ValueError("noise impact finding provenance must be MetricProvenance")
        require_nonempty_identifier(self.summary, label="noise impact finding summary")
        if self.kind is NoiseImpactEventKind.IDLE_DECOHERENCE and self.idle is None:
            raise ValueError("idle findings require idle evidence")
        if self.kind is NoiseImpactEventKind.GATE_CHANNEL and self.gate is None:
            raise ValueError("gate findings require gate evidence")
        if self.kind is NoiseImpactEventKind.READOUT_DISTORTION and self.readout is None:
            raise ValueError("readout findings require readout evidence")

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "provenance": self.provenance.value,
            "summary": self.summary,
            "idle": self.idle.to_dict() if self.idle is not None else None,
            "gate": self.gate.to_dict() if self.gate is not None else None,
            "readout": self.readout.to_dict() if self.readout is not None else None,
        }


@dataclass(frozen=True, slots=True)
class NoiseImpactLimitations:
    statements: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.statements, tuple) or not self.statements:
            raise ValueError("noise impact limitations statements must be a non-empty tuple")
        for statement in self.statements:
            require_nonempty_identifier(statement, label="noise impact limitation")

    def to_dict(self) -> dict[str, object]:
        return {"statements": list(self.statements)}


@dataclass(frozen=True, slots=True)
class NoiseImpactReport:
    comparison: NoiseImpactComparisonProvenance
    ideal_state: DensityStateReport
    noisy_state: DensityStateReport
    metrics: tuple[NoiseImpactMetric, ...]
    ideal_physical_distribution: tuple[float, ...]
    noisy_physical_distribution: tuple[float, ...]
    reported_distribution: tuple[float, ...]
    event_findings: tuple[NoiseImpactEventFinding, ...]
    limitations: NoiseImpactLimitations
    schema_version: int = NOISE_IMPACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.comparison, NoiseImpactComparisonProvenance):
            raise ValueError("noise impact comparison must be NoiseImpactComparisonProvenance")
        for report, label in ((self.ideal_state, "ideal_state"), (self.noisy_state, "noisy_state")):
            if not isinstance(report, DensityStateReport):
                raise ValueError(f"noise impact {label} must be DensityStateReport")
        if not isinstance(self.metrics, tuple) or not all(isinstance(metric, NoiseImpactMetric) for metric in self.metrics):
            raise ValueError("noise impact metrics must contain NoiseImpactMetric values")
        if not isinstance(self.event_findings, tuple) or not all(
            isinstance(finding, NoiseImpactEventFinding) for finding in self.event_findings
        ):
            raise ValueError("noise impact event_findings must contain NoiseImpactEventFinding values")
        if not isinstance(self.limitations, NoiseImpactLimitations):
            raise ValueError("noise impact limitations must be NoiseImpactLimitations")
        if (
            isinstance(self.schema_version, bool)
            or not isinstance(self.schema_version, int)
            or self.schema_version != NOISE_IMPACT_SCHEMA_VERSION
        ):
            raise ValueError("noise impact schema_version must match supported schema")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "comparison": self.comparison.to_dict(),
            "ideal_state": self.ideal_state.to_dict(),
            "noisy_state": self.noisy_state.to_dict(),
            "metrics": [metric.to_dict() for metric in self.metrics],
            "ideal_physical_distribution": list(self.ideal_physical_distribution),
            "noisy_physical_distribution": list(self.noisy_physical_distribution),
            "reported_distribution": list(self.reported_distribution),
            "event_findings": [finding.to_dict() for finding in self.event_findings],
            "limitations": self.limitations.to_dict(),
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


def inspect_density_state(
    density_matrix: tuple[tuple[complex, ...], ...],
    *,
    qubit_count: int,
) -> DensityStateReport:
    dimension = 1 << qubit_count
    _validate_density_matrix_shape(density_matrix, dimension=dimension)
    populations = tuple(float(density_matrix[index][index].real) for index in range(dimension))
    purity = _purity(density_matrix)
    l1_coherence = _l1_coherence(density_matrix)
    return DensityStateReport(
        qubit_count=qubit_count,
        dimension=dimension,
        computational_basis_populations=populations,
        purity=purity,
        l1_coherence=l1_coherence,
    )


def build_noise_impact_report(
    *,
    comparison: NoiseImpactComparisonProvenance,
    ideal_density_matrix: tuple[tuple[complex, ...], ...],
    noisy_density_matrix: tuple[tuple[complex, ...], ...],
    qubit_count: int,
    ideal_physical_distribution: tuple[float, ...],
    noisy_physical_distribution: tuple[float, ...],
    reported_distribution: tuple[float, ...],
    idle_events: tuple[IdleDecoherenceEvent, ...] = (),
    gate_events: tuple[GateNoiseApplicationEvent, ...] = (),
    readout_channel: dict[str, object] | None = None,
) -> NoiseImpactReport:
    ideal_state = inspect_density_state(ideal_density_matrix, qubit_count=qubit_count)
    noisy_state = inspect_density_state(noisy_density_matrix, qubit_count=qubit_count)

    if len(ideal_physical_distribution) != len(noisy_physical_distribution) or len(noisy_physical_distribution) != len(reported_distribution):
        raise ValueError("noise impact distributions must have matching lengths")

    hs_distance = _hilbert_schmidt_distance(noisy_density_matrix, ideal_density_matrix)
    population_tvd = _total_variation_distance(
        ideal_state.computational_basis_populations,
        noisy_state.computational_basis_populations,
    )
    coherence_delta = noisy_state.l1_coherence - ideal_state.l1_coherence
    abs_coherence_mag_change = _off_diagonal_magnitude_delta(noisy_density_matrix, ideal_density_matrix)
    purity_delta = noisy_state.purity - ideal_state.purity
    physical_output_tvd = _total_variation_distance(ideal_physical_distribution, noisy_physical_distribution)
    readout_distortion_tvd = _total_variation_distance(noisy_physical_distribution, reported_distribution)

    metrics = (
        NoiseImpactMetric(
            name="hilbert_schmidt_distance",
            value=hs_distance,
            definition="sqrt(sum_ij |rho_noisy[i,j] - rho_ideal[i,j]|^2)",
            tolerance=comparison.metric_tolerance,
            provenance=MetricProvenance.DERIVED,
            scope=NoiseImpactScope.STATE,
        ),
        NoiseImpactMetric(
            name="computational_basis_population_tvd",
            value=population_tvd,
            definition="0.5 * sum_i |p_noisy[i] - p_ideal[i]| where p_i = rho[i,i]",
            tolerance=comparison.metric_tolerance,
            provenance=MetricProvenance.DERIVED,
            scope=NoiseImpactScope.STATE,
            basis_dependent=True,
            basis="computational",
        ),
        NoiseImpactMetric(
            name="ideal_l1_coherence",
            value=ideal_state.l1_coherence,
            definition="C_l1(rho) = sum_(i != j) |rho[i,j]|",
            tolerance=comparison.metric_tolerance,
            provenance=MetricProvenance.OBSERVED,
            scope=NoiseImpactScope.STATE,
            basis_dependent=True,
            basis="computational",
        ),
        NoiseImpactMetric(
            name="noisy_l1_coherence",
            value=noisy_state.l1_coherence,
            definition="C_l1(rho) = sum_(i != j) |rho[i,j]|",
            tolerance=comparison.metric_tolerance,
            provenance=MetricProvenance.OBSERVED,
            scope=NoiseImpactScope.STATE,
            basis_dependent=True,
            basis="computational",
        ),
        NoiseImpactMetric(
            name="delta_l1_coherence",
            value=coherence_delta,
            definition="C_l1(rho_noisy) - C_l1(rho_ideal)",
            tolerance=comparison.metric_tolerance,
            provenance=MetricProvenance.DERIVED,
            scope=NoiseImpactScope.STATE,
            basis_dependent=True,
            basis="computational",
        ),
        NoiseImpactMetric(
            name="absolute_l1_coherence_magnitude_change",
            value=abs_coherence_mag_change,
            definition="sum_(i != j) ||rho_noisy[i,j]| - |rho_ideal[i,j]||",
            tolerance=comparison.metric_tolerance,
            provenance=MetricProvenance.DERIVED,
            scope=NoiseImpactScope.STATE,
            basis_dependent=True,
            basis="computational",
        ),
        NoiseImpactMetric(
            name="ideal_purity",
            value=ideal_state.purity,
            definition="Tr(rho_ideal^2)",
            tolerance=comparison.metric_tolerance,
            provenance=MetricProvenance.OBSERVED,
            scope=NoiseImpactScope.STATE,
        ),
        NoiseImpactMetric(
            name="noisy_purity",
            value=noisy_state.purity,
            definition="Tr(rho_noisy^2)",
            tolerance=comparison.metric_tolerance,
            provenance=MetricProvenance.OBSERVED,
            scope=NoiseImpactScope.STATE,
        ),
        NoiseImpactMetric(
            name="delta_purity",
            value=purity_delta,
            definition="Tr(rho_noisy^2) - Tr(rho_ideal^2)",
            tolerance=comparison.metric_tolerance,
            provenance=MetricProvenance.DERIVED,
            scope=NoiseImpactScope.STATE,
        ),
        NoiseImpactMetric(
            name="physical_output_tvd",
            value=physical_output_tvd,
            definition="TVD(ideal physical distribution, noisy physical distribution)",
            tolerance=comparison.metric_tolerance,
            provenance=MetricProvenance.DERIVED,
            scope=NoiseImpactScope.OUTPUT_DISTRIBUTION,
        ),
        NoiseImpactMetric(
            name="readout_distortion_tvd",
            value=readout_distortion_tvd,
            definition="TVD(noisy physical distribution, reported/readout distribution)",
            tolerance=comparison.metric_tolerance,
            provenance=MetricProvenance.DERIVED,
            scope=NoiseImpactScope.OUTPUT_DISTRIBUTION,
        ),
    )

    findings: list[NoiseImpactEventFinding] = []
    for event in idle_events:
        findings.append(
            NoiseImpactEventFinding(
                kind=NoiseImpactEventKind.IDLE_DECOHERENCE,
                provenance=MetricProvenance.OBSERVED,
                summary="Modeled idle-decoherence exposure event",
                idle=IdleNoiseImpactEvidence(
                    slot=event.slot,
                    start_ns=event.interval.start_ns,
                    end_ns=event.interval.end_ns,
                    duration_ns=event.interval.duration_ns,
                    gamma1=event.amplitude_damping_probability,
                    p_phi=event.phase_damping_probability,
                    mode=event.provenance.mode,
                    t1_ns=event.provenance.t1_ns,
                    t2_ns=event.provenance.t2_ns,
                    tphi_inverse_per_ns=event.provenance.tphi_inverse_per_ns,
                ),
            )
        )
    for event in gate_events:
        findings.append(
            NoiseImpactEventFinding(
                kind=NoiseImpactEventKind.GATE_CHANNEL,
                provenance=MetricProvenance.OBSERVED,
                summary="Modeled post-gate channel application event",
                gate=GateNoiseImpactEvidence(
                    operation_id=event.operation_id,
                    target_slot=event.target_slot,
                    gate=event.gate.value,
                    channel=event.channel.to_dict(),
                    application_order=event.application_order,
                    application_ordering=event.application_ordering,
                ),
            )
        )
    if readout_channel is not None:
        findings.append(
            NoiseImpactEventFinding(
                kind=NoiseImpactEventKind.READOUT_DISTORTION,
                provenance=MetricProvenance.OBSERVED,
                summary="Modeled classical readout distortion evidence",
                readout=ReadoutDistortionEvidence(
                    channel=readout_channel,
                    physical_vs_reported_tvd=readout_distortion_tvd,
                ),
            )
        )

    limitations = NoiseImpactLimitations(
        statements=(
            "Hilbert-Schmidt distance is a deterministic diagnostic metric; it is not an operational error probability.",
            "Computational-basis population and l1 coherence metrics are basis dependent.",
            "Readout distortion modifies reported classical outcomes and is not quantum-state damage.",
            "Noise effects are generally non-additive. Event evidence identifies modeled noise applications and parameters; it does not partition total state deviation into causal percentages.",
            "Purity change is reported relative to the matched ideal baseline; the ideal baseline may already be mixed due to execution semantics.",
        )
    )

    return NoiseImpactReport(
        comparison=comparison,
        ideal_state=ideal_state,
        noisy_state=noisy_state,
        metrics=metrics,
        ideal_physical_distribution=ideal_physical_distribution,
        noisy_physical_distribution=noisy_physical_distribution,
        reported_distribution=reported_distribution,
        event_findings=tuple(findings),
        limitations=limitations,
    )


def _hilbert_schmidt_distance(
    left: tuple[tuple[complex, ...], ...],
    right: tuple[tuple[complex, ...], ...],
) -> float:
    total = 0.0
    for row_left, row_right in zip(left, right, strict=True):
        for value_left, value_right in zip(row_left, row_right, strict=True):
            delta = value_left - value_right
            total += (delta.real * delta.real) + (delta.imag * delta.imag)
    return sqrt(total)


def _purity(density_matrix: tuple[tuple[complex, ...], ...]) -> float:
    dimension = len(density_matrix)
    total = 0 + 0j
    for row in range(dimension):
        for col in range(dimension):
            total += density_matrix[row][col] * density_matrix[col][row]
    return float(total.real)


def _l1_coherence(density_matrix: tuple[tuple[complex, ...], ...]) -> float:
    total = 0.0
    for row, values in enumerate(density_matrix):
        for col, value in enumerate(values):
            if row == col:
                continue
            total += abs(value)
    return total


def _off_diagonal_magnitude_delta(
    noisy: tuple[tuple[complex, ...], ...],
    ideal: tuple[tuple[complex, ...], ...],
) -> float:
    total = 0.0
    for row in range(len(noisy)):
        for col in range(len(noisy[row])):
            if row == col:
                continue
            total += abs(abs(noisy[row][col]) - abs(ideal[row][col]))
    return total


def _total_variation_distance(
    left: tuple[float, ...],
    right: tuple[float, ...],
) -> float:
    if len(left) != len(right):
        raise ValueError("total variation distance requires distributions of equal length")
    return 0.5 * sum(abs(l_value - r_value) for l_value, r_value in zip(left, right, strict=True))


def _validate_density_matrix_shape(
    density_matrix: tuple[tuple[complex, ...], ...],
    *,
    dimension: int,
) -> None:
    if not isinstance(density_matrix, tuple) or len(density_matrix) != dimension:
        raise ValueError("density matrix must be a tuple with dimension 2**qubit_count")
    for row in density_matrix:
        if not isinstance(row, tuple) or len(row) != dimension:
            raise ValueError("density matrix rows must match matrix dimension")
        for value in row:
            if not isinstance(value, complex) or not isfinite(value.real) or not isfinite(value.imag):
                raise ValueError("density matrix entries must be finite complex values")


__all__ = [
    "DensityStateReport",
    "MetricProvenance",
    "NoiseImpactComparisonProvenance",
    "NoiseImpactEventFinding",
    "NoiseImpactEventKind",
    "NoiseImpactLimitations",
    "NoiseImpactMetric",
    "NoiseImpactReport",
    "NoiseImpactScope",
    "NOISE_IMPACT_ABS_TOLERANCE",
    "NOISE_IMPACT_SCHEMA_VERSION",
    "build_noise_impact_report",
    "inspect_density_state",
]
