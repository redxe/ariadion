from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isclose, isfinite, sqrt
from typing import Final

from ariadion_core import ProgramId, canonical_json, require_nonempty_identifier
from ariadion_noise import (
    AmplitudeDampingChannel,
    BinaryReadoutChannel,
    BitFlipChannel,
    DepolarizingChannel,
    PhaseDampingChannel,
    PhaseFlipChannel,
    QuantumChannel,
)
from ariadion_simulator import (
    GateNoiseApplicationEvent,
    IdleDecoherenceEvent,
    ValidatedDensityState,
)

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


class NoiseImpactBaselineMode(str, Enum):
    IDEAL_NOISE_DISABLED_REPLAY = "ideal_noise_disabled_replay"


@dataclass(frozen=True, slots=True)
class NoiseImpactScheduleSummary:
    program_id: ProgramId
    operation_fingerprint: tuple[
        tuple[str, str, tuple[int, ...], tuple[int, ...], float | None],
        ...,
    ]
    peak_duration_ns: float

    def __post_init__(self) -> None:
        require_nonempty_identifier(self.program_id, label="noise impact schedule program ID")
        if not isinstance(self.operation_fingerprint, tuple):
            raise ValueError("noise impact schedule operation_fingerprint must be a tuple")
        for entry in self.operation_fingerprint:
            if (
                not isinstance(entry, tuple)
                or len(entry) != 5
                or not isinstance(entry[0], str)
                or not isinstance(entry[1], str)
                or not isinstance(entry[2], tuple)
                or not isinstance(entry[3], tuple)
            ):
                raise ValueError(
                    "noise impact schedule operation_fingerprint must contain "
                    "(operation_id, opcode, targets, controls, angle_radians) tuples"
                )
            if not all(isinstance(target, int) and target >= 0 for target in entry[2]):
                raise ValueError(
                    "noise impact schedule operation_fingerprint targets must be "
                    "non-negative integers"
                )
            if not all(isinstance(control, int) and control >= 0 for control in entry[3]):
                raise ValueError(
                    "noise impact schedule operation_fingerprint controls must be "
                    "non-negative integers"
                )
            if entry[4] is not None and (
                isinstance(entry[4], bool)
                or not isinstance(entry[4], (int, float))
                or not isfinite(float(entry[4]))
            ):
                raise ValueError(
                    "noise impact schedule operation_fingerprint angle_radians must be "
                    "None or a finite number"
                )
        if (
            isinstance(self.peak_duration_ns, bool)
            or not isinstance(self.peak_duration_ns, (int, float))
            or not isfinite(float(self.peak_duration_ns))
            or self.peak_duration_ns < 0
        ):
            raise ValueError(
                "noise impact schedule peak_duration_ns must be a non-negative finite number"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "program_id": self.program_id,
            "operation_fingerprint": [
                {
                    "operation_id": operation_id,
                    "opcode": opcode,
                    "targets": list(targets),
                    "controls": list(controls),
                    "angle_radians": angle_radians,
                }
                for operation_id, opcode, targets, controls, angle_radians in self.operation_fingerprint
            ],
            "peak_duration_ns": float(self.peak_duration_ns),
        }


@dataclass(frozen=True, slots=True)
class IdleDecoherenceProfileSnapshot:
    t1_ns: float | None
    t2_ns: float | None

    def __post_init__(self) -> None:
        if self.t1_ns is None and self.t2_ns is None:
            raise ValueError("idle decoherence snapshot requires t1_ns or t2_ns")
        for value, label in ((self.t1_ns, "t1_ns"), (self.t2_ns, "t2_ns")):
            if value is None:
                continue
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not isfinite(float(value))
                or float(value) <= 0
            ):
                raise ValueError(
                    f"idle decoherence snapshot {label} must be a positive finite number"
                )
        if self.t1_ns is not None and self.t2_ns is not None and self.t2_ns > 2 * self.t1_ns:
            raise ValueError("idle decoherence snapshot t2_ns must be <= 2 * t1_ns")

    def to_dict(self) -> dict[str, float | None]:
        return {"t1_ns": self.t1_ns, "t2_ns": self.t2_ns}


@dataclass(frozen=True, slots=True)
class BitFlipChannelSnapshot:
    probability: float

    def __post_init__(self) -> None:
        _validate_probability(self.probability, label="bit_flip probability")

    def to_dict(self) -> dict[str, object]:
        return {"kind": "bit_flip", "probability": self.probability}


@dataclass(frozen=True, slots=True)
class PhaseFlipChannelSnapshot:
    probability: float

    def __post_init__(self) -> None:
        _validate_probability(self.probability, label="phase_flip probability")

    def to_dict(self) -> dict[str, object]:
        return {"kind": "phase_flip", "probability": self.probability}


@dataclass(frozen=True, slots=True)
class DepolarizingChannelSnapshot:
    probability: float

    def __post_init__(self) -> None:
        _validate_probability(self.probability, label="depolarizing probability")

    def to_dict(self) -> dict[str, object]:
        return {"kind": "depolarizing", "probability": self.probability}


@dataclass(frozen=True, slots=True)
class AmplitudeDampingChannelSnapshot:
    probability: float

    def __post_init__(self) -> None:
        _validate_probability(self.probability, label="amplitude_damping probability")

    def to_dict(self) -> dict[str, object]:
        return {"kind": "amplitude_damping", "probability": self.probability}


@dataclass(frozen=True, slots=True)
class PhaseDampingChannelSnapshot:
    probability: float

    def __post_init__(self) -> None:
        _validate_probability(self.probability, label="phase_damping probability")

    def to_dict(self) -> dict[str, object]:
        return {"kind": "phase_damping", "probability": self.probability}


GateChannelSnapshot = (
    BitFlipChannelSnapshot
    | PhaseFlipChannelSnapshot
    | DepolarizingChannelSnapshot
    | AmplitudeDampingChannelSnapshot
    | PhaseDampingChannelSnapshot
)


@dataclass(frozen=True, slots=True)
class BinaryReadoutChannelSnapshot:
    p_one_given_zero: float
    p_zero_given_one: float

    def __post_init__(self) -> None:
        _validate_probability(
            self.p_one_given_zero,
            label="binary_readout p_one_given_zero",
        )
        _validate_probability(
            self.p_zero_given_one,
            label="binary_readout p_zero_given_one",
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": "binary_readout",
            "p_one_given_zero": self.p_one_given_zero,
            "p_zero_given_one": self.p_zero_given_one,
        }


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
        min_purity = 1.0 / self.dimension
        if self.purity < min_purity - NOISE_IMPACT_ABS_TOLERANCE or self.purity > 1.0 + NOISE_IMPACT_ABS_TOLERANCE:
            raise ValueError(
                "density state report purity must be within physical bounds [1/d, 1] "
                "within tolerance"
            )
        if self.l1_coherence < -NOISE_IMPACT_ABS_TOLERANCE:
            raise ValueError(
                "density state report l1_coherence must be non-negative within tolerance"
            )
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
    noisy_backend_id: str
    ideal_backend_id: str
    ideal_baseline_mode: NoiseImpactBaselineMode
    noisy_schedule: NoiseImpactScheduleSummary | None
    noisy_idle_decoherence: IdleDecoherenceProfileSnapshot | None
    ideal_baseline_derivation: str
    metric_tolerance: float = NOISE_IMPACT_ABS_TOLERANCE

    def __post_init__(self) -> None:
        require_nonempty_identifier(self.circuit_id, label="noise impact circuit ID")
        require_nonempty_identifier(self.representation, label="noise impact representation")
        require_nonempty_identifier(self.noisy_backend_id, label="noise impact noisy backend ID")
        require_nonempty_identifier(self.ideal_backend_id, label="noise impact ideal backend ID")
        if not isinstance(self.ideal_baseline_mode, NoiseImpactBaselineMode):
            raise ValueError(
                "noise impact ideal_baseline_mode must be NoiseImpactBaselineMode"
            )
        if self.noisy_schedule is not None and not isinstance(
            self.noisy_schedule,
            NoiseImpactScheduleSummary,
        ):
            raise ValueError(
                "noise impact noisy_schedule must be NoiseImpactScheduleSummary or None"
            )
        if self.noisy_idle_decoherence is not None and not isinstance(
            self.noisy_idle_decoherence,
            IdleDecoherenceProfileSnapshot,
        ):
            raise ValueError(
                "noise impact noisy_idle_decoherence must be "
                "IdleDecoherenceProfileSnapshot or None"
            )
        if (self.noisy_schedule is None) != (self.noisy_idle_decoherence is None):
            raise ValueError(
                "noise impact noisy_schedule and noisy_idle_decoherence must be paired"
            )
        if self.noisy_schedule is not None and self.noisy_schedule.program_id != self.circuit_id:
            raise ValueError(
                "noise impact noisy_schedule program_id must match comparison circuit_id"
            )
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
            "noisy_backend_id": self.noisy_backend_id,
            "ideal_backend_id": self.ideal_backend_id,
            "ideal_baseline_mode": self.ideal_baseline_mode.value,
            "noisy_schedule": (
                self.noisy_schedule.to_dict() if self.noisy_schedule is not None else None
            ),
            "noisy_idle_decoherence": (
                self.noisy_idle_decoherence.to_dict()
                if self.noisy_idle_decoherence is not None
                else None
            ),
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
    channel: GateChannelSnapshot
    application_order: int
    application_ordering: str

    def __post_init__(self) -> None:
        require_nonempty_identifier(self.operation_id, label="gate noise evidence operation_id")
        if (
            isinstance(self.target_slot, bool)
            or not isinstance(self.target_slot, int)
            or self.target_slot < 0
        ):
            raise ValueError("gate noise evidence target_slot must be a non-negative integer")
        require_nonempty_identifier(self.gate, label="gate noise evidence gate")
        if not isinstance(
            self.channel,
            (
                BitFlipChannelSnapshot,
                PhaseFlipChannelSnapshot,
                DepolarizingChannelSnapshot,
                AmplitudeDampingChannelSnapshot,
                PhaseDampingChannelSnapshot,
            ),
        ):
            raise ValueError("gate noise evidence channel must be a supported channel snapshot")
        if (
            isinstance(self.application_order, bool)
            or not isinstance(self.application_order, int)
            or self.application_order < 0
        ):
            raise ValueError("gate noise evidence application_order must be a non-negative integer")
        if self.application_ordering != "ideal_then_channel":
            raise ValueError(
                "gate noise evidence application_ordering must be 'ideal_then_channel'"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "operation_id": self.operation_id,
            "target_slot": self.target_slot,
            "gate": self.gate,
            "channel": self.channel.to_dict(),
            "application_order": self.application_order,
            "application_ordering": self.application_ordering,
        }


@dataclass(frozen=True, slots=True)
class ReadoutDistortionEvidence:
    channel: BinaryReadoutChannelSnapshot
    physical_vs_reported_tvd: float

    def __post_init__(self) -> None:
        if not isinstance(self.channel, BinaryReadoutChannelSnapshot):
            raise ValueError("readout distortion evidence channel must be BinaryReadoutChannelSnapshot")
        if (
            isinstance(self.physical_vs_reported_tvd, bool)
            or not isinstance(self.physical_vs_reported_tvd, (int, float))
            or not isfinite(float(self.physical_vs_reported_tvd))
            or float(self.physical_vs_reported_tvd) < -NOISE_IMPACT_ABS_TOLERANCE
        ):
            raise ValueError(
                "readout distortion evidence physical_vs_reported_tvd must be finite and non-negative"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "channel": self.channel.to_dict(),
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
        evidence_count = sum(
            value is not None for value in (self.idle, self.gate, self.readout)
        )
        if evidence_count != 1:
            raise ValueError(
                "noise impact findings must contain exactly one event evidence payload"
            )
        if self.kind is NoiseImpactEventKind.IDLE_DECOHERENCE:
            if self.idle is None or self.gate is not None or self.readout is not None:
                raise ValueError("idle findings must include only idle evidence")
        if self.kind is NoiseImpactEventKind.GATE_CHANNEL:
            if self.gate is None or self.idle is not None or self.readout is not None:
                raise ValueError("gate findings must include only gate evidence")
        if self.kind is NoiseImpactEventKind.READOUT_DISTORTION:
            if self.readout is None or self.idle is not None or self.gate is not None:
                raise ValueError("readout findings must include only readout evidence")

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
    ideal_physical_distribution: tuple[float, ...] | None
    noisy_physical_distribution: tuple[float, ...] | None
    reported_distribution: tuple[float, ...] | None
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
        metric_names = tuple(metric.name for metric in self.metrics)
        if len(metric_names) != len(set(metric_names)):
            raise ValueError("noise impact metric names must be unique")
        if not isinstance(self.event_findings, tuple) or not all(
            isinstance(finding, NoiseImpactEventFinding) for finding in self.event_findings
        ):
            raise ValueError("noise impact event_findings must contain NoiseImpactEventFinding values")
        _validate_output_distribution_bundle(
            ideal=self.ideal_physical_distribution,
            noisy=self.noisy_physical_distribution,
            reported=self.reported_distribution,
        )
        if not isinstance(self.limitations, NoiseImpactLimitations):
            raise ValueError("noise impact limitations must be NoiseImpactLimitations")
        has_output_distributions = self.ideal_physical_distribution is not None
        output_metric_names = {"physical_output_tvd", "readout_distortion_tvd"}
        present_output_metrics = {
            metric.name for metric in self.metrics if metric.name in output_metric_names
        }
        if has_output_distributions and present_output_metrics != output_metric_names:
            raise ValueError(
                "noise impact reports with output distributions must include both output TVD metrics"
            )
        if not has_output_distributions and present_output_metrics:
            raise ValueError(
                "noise impact reports without output distributions must omit output TVD metrics"
            )
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
            "ideal_physical_distribution": (
                list(self.ideal_physical_distribution)
                if self.ideal_physical_distribution is not None
                else None
            ),
            "noisy_physical_distribution": (
                list(self.noisy_physical_distribution)
                if self.noisy_physical_distribution is not None
                else None
            ),
            "reported_distribution": (
                list(self.reported_distribution)
                if self.reported_distribution is not None
                else None
            ),
            "event_findings": [finding.to_dict() for finding in self.event_findings],
            "limitations": self.limitations.to_dict(),
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


def inspect_density_state(
    density_matrix: ValidatedDensityState | tuple[tuple[int | float | complex, ...], ...],
    *,
    qubit_count: int | None = None,
) -> DensityStateReport:
    validated = _coerce_validated_density_state(
        density_matrix,
        qubit_count=qubit_count,
        label="density state inspection",
    )
    matrix = validated.density_matrix
    dimension = validated.dimension
    populations = tuple(float(matrix[index][index].real) for index in range(dimension))
    purity = _purity(matrix)
    l1_coherence = _l1_coherence(matrix)
    return DensityStateReport(
        qubit_count=validated.qubit_count,
        dimension=dimension,
        computational_basis_populations=populations,
        purity=purity,
        l1_coherence=l1_coherence,
    )


def build_noise_impact_report(
    *,
    comparison: NoiseImpactComparisonProvenance,
    ideal_density_matrix: ValidatedDensityState | tuple[tuple[int | float | complex, ...], ...],
    noisy_density_matrix: ValidatedDensityState | tuple[tuple[int | float | complex, ...], ...],
    qubit_count: int | None = None,
    ideal_physical_distribution: tuple[float, ...] | None,
    noisy_physical_distribution: tuple[float, ...] | None,
    reported_distribution: tuple[float, ...] | None,
    idle_events: tuple[IdleDecoherenceEvent, ...] = (),
    gate_events: tuple[GateNoiseApplicationEvent, ...] = (),
    readout_channel: BinaryReadoutChannel | BinaryReadoutChannelSnapshot | dict[str, object] | None = None,
) -> NoiseImpactReport:
    ideal_validated = _coerce_validated_density_state(
        ideal_density_matrix,
        qubit_count=qubit_count,
        label="ideal density matrix",
    )
    noisy_validated = _coerce_validated_density_state(
        noisy_density_matrix,
        qubit_count=qubit_count,
        label="noisy density matrix",
    )
    if ideal_validated.qubit_count != noisy_validated.qubit_count:
        raise ValueError("noise impact ideal and noisy density states must have matching qubit_count")
    if qubit_count is not None and ideal_validated.qubit_count != qubit_count:
        raise ValueError("noise impact qubit_count must match validated density states")

    ideal_state = inspect_density_state(ideal_validated)
    noisy_state = inspect_density_state(noisy_validated)
    ideal_matrix = ideal_validated.density_matrix
    noisy_matrix = noisy_validated.density_matrix

    _validate_output_distribution_bundle(
        ideal=ideal_physical_distribution,
        noisy=noisy_physical_distribution,
        reported=reported_distribution,
    )

    hs_distance = _hilbert_schmidt_distance(noisy_matrix, ideal_matrix)
    population_tvd = _total_variation_distance(
        ideal_state.computational_basis_populations,
        noisy_state.computational_basis_populations,
    )
    coherence_delta = noisy_state.l1_coherence - ideal_state.l1_coherence
    abs_coherence_mag_change = _off_diagonal_magnitude_delta(noisy_matrix, ideal_matrix)
    purity_delta = noisy_state.purity - ideal_state.purity
    physical_output_tvd: float | None = None
    readout_distortion_tvd: float | None = None
    if (
        ideal_physical_distribution is not None
        and noisy_physical_distribution is not None
        and reported_distribution is not None
    ):
        physical_output_tvd = _total_variation_distance(
            ideal_physical_distribution,
            noisy_physical_distribution,
        )
        readout_distortion_tvd = _total_variation_distance(
            noisy_physical_distribution,
            reported_distribution,
        )

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
            provenance=MetricProvenance.DERIVED,
            scope=NoiseImpactScope.STATE,
            basis_dependent=True,
            basis="computational",
        ),
        NoiseImpactMetric(
            name="noisy_l1_coherence",
            value=noisy_state.l1_coherence,
            definition="C_l1(rho) = sum_(i != j) |rho[i,j]|",
            tolerance=comparison.metric_tolerance,
            provenance=MetricProvenance.DERIVED,
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
            provenance=MetricProvenance.DERIVED,
            scope=NoiseImpactScope.STATE,
        ),
        NoiseImpactMetric(
            name="noisy_purity",
            value=noisy_state.purity,
            definition="Tr(rho_noisy^2)",
            tolerance=comparison.metric_tolerance,
            provenance=MetricProvenance.DERIVED,
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
    )
    if physical_output_tvd is not None:
        metrics += (
            NoiseImpactMetric(
                name="physical_output_tvd",
                value=physical_output_tvd,
                definition="TVD(ideal physical distribution, noisy physical distribution)",
                tolerance=comparison.metric_tolerance,
                provenance=MetricProvenance.DERIVED,
                scope=NoiseImpactScope.OUTPUT_DISTRIBUTION,
            ),
        )
    if readout_distortion_tvd is not None:
        metrics += (
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
                    channel=_snapshot_gate_channel(event.channel),
                    application_order=event.application_order,
                    application_ordering=event.application_ordering,
                ),
            )
        )
    readout_snapshot = _coerce_readout_channel_snapshot(readout_channel)
    if readout_snapshot is not None and readout_distortion_tvd is not None:
        findings.append(
            NoiseImpactEventFinding(
                kind=NoiseImpactEventKind.READOUT_DISTORTION,
                provenance=MetricProvenance.OBSERVED,
                summary="Modeled classical readout distortion evidence",
                readout=ReadoutDistortionEvidence(
                    channel=readout_snapshot,
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


def _coerce_validated_density_state(
    value: ValidatedDensityState | tuple[tuple[int | float | complex, ...], ...],
    *,
    qubit_count: int | None,
    label: str,
) -> ValidatedDensityState:
    if isinstance(value, ValidatedDensityState):
        if qubit_count is not None and value.qubit_count != qubit_count:
            raise ValueError(f"{label} qubit_count does not match validated density state")
        return value
    if qubit_count is None:
        raise ValueError(f"{label} requires qubit_count when a raw matrix is provided")
    return ValidatedDensityState.from_matrix(value, qubit_count=qubit_count)


def _validate_probability(value: float, *, label: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not isfinite(float(value))
        or float(value) < 0
        or float(value) > 1
    ):
        raise ValueError(f"{label} must be in [0, 1]")


def _snapshot_gate_channel(channel: QuantumChannel) -> GateChannelSnapshot:
    if isinstance(channel, BitFlipChannel):
        return BitFlipChannelSnapshot(channel.probability)
    if isinstance(channel, PhaseFlipChannel):
        return PhaseFlipChannelSnapshot(channel.probability)
    if isinstance(channel, DepolarizingChannel):
        return DepolarizingChannelSnapshot(channel.probability)
    if isinstance(channel, AmplitudeDampingChannel):
        return AmplitudeDampingChannelSnapshot(channel.probability)
    if isinstance(channel, PhaseDampingChannel):
        return PhaseDampingChannelSnapshot(channel.probability)
    raise ValueError("unsupported gate channel type for noise impact evidence")


def _coerce_readout_channel_snapshot(
    channel: BinaryReadoutChannel | BinaryReadoutChannelSnapshot | dict[str, object] | None,
) -> BinaryReadoutChannelSnapshot | None:
    if channel is None:
        return None
    if isinstance(channel, BinaryReadoutChannelSnapshot):
        return channel
    if isinstance(channel, BinaryReadoutChannel):
        return BinaryReadoutChannelSnapshot(
            p_one_given_zero=channel.p_one_given_zero,
            p_zero_given_one=channel.p_zero_given_one,
        )
    if isinstance(channel, dict):
        if set(channel.keys()) != {"kind", "p_one_given_zero", "p_zero_given_one"}:
            raise ValueError(
                "noise impact readout_channel dict must contain kind, p_one_given_zero, and p_zero_given_one"
            )
        if channel.get("kind") != "binary_readout":
            raise ValueError("noise impact readout_channel kind must be 'binary_readout'")
        return BinaryReadoutChannelSnapshot(
            p_one_given_zero=channel["p_one_given_zero"],  # type: ignore[arg-type]
            p_zero_given_one=channel["p_zero_given_one"],  # type: ignore[arg-type]
        )
    raise ValueError(
        "noise impact readout_channel must be BinaryReadoutChannel, "
        "BinaryReadoutChannelSnapshot, dict, or None"
    )


def _validate_probability_distribution(
    distribution: tuple[float, ...],
    *,
    label: str,
) -> None:
    if not isinstance(distribution, tuple) or not distribution:
        raise ValueError(f"noise impact {label} distribution must be a non-empty tuple")
    total = 0.0
    for value in distribution:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(float(value)):
            raise ValueError(f"noise impact {label} distribution entries must be finite numbers")
        if value < -NOISE_IMPACT_ABS_TOLERANCE:
            raise ValueError(
                f"noise impact {label} distribution entries must be non-negative within tolerance"
            )
        total += float(value)
    if not isclose(total, 1.0, rel_tol=0.0, abs_tol=NOISE_IMPACT_ABS_TOLERANCE):
        raise ValueError(
            f"noise impact {label} distribution entries must sum to one within tolerance"
        )


def _validate_output_distribution_bundle(
    *,
    ideal: tuple[float, ...] | None,
    noisy: tuple[float, ...] | None,
    reported: tuple[float, ...] | None,
) -> None:
    bundle = (ideal, noisy, reported)
    if all(value is None for value in bundle):
        return
    if any(value is None for value in bundle):
        raise ValueError(
            "noise impact output distributions must be all present or all absent"
        )
    assert ideal is not None
    assert noisy is not None
    assert reported is not None
    _validate_probability_distribution(ideal, label="ideal")
    _validate_probability_distribution(noisy, label="noisy")
    _validate_probability_distribution(reported, label="reported")
    if len(ideal) != len(noisy) or len(noisy) != len(reported):
        raise ValueError("noise impact distributions must have matching lengths")


__all__ = [
    "AmplitudeDampingChannelSnapshot",
    "BinaryReadoutChannelSnapshot",
    "BitFlipChannelSnapshot",
    "DepolarizingChannelSnapshot",
    "DensityStateReport",
    "IdleDecoherenceProfileSnapshot",
    "MetricProvenance",
    "NoiseImpactBaselineMode",
    "NoiseImpactComparisonProvenance",
    "NoiseImpactEventFinding",
    "NoiseImpactEventKind",
    "NoiseImpactLimitations",
    "NoiseImpactMetric",
    "NoiseImpactReport",
    "NoiseImpactScheduleSummary",
    "NoiseImpactScope",
    "NOISE_IMPACT_ABS_TOLERANCE",
    "NOISE_IMPACT_SCHEMA_VERSION",
    "PhaseDampingChannelSnapshot",
    "PhaseFlipChannelSnapshot",
    "build_noise_impact_report",
    "inspect_density_state",
]
