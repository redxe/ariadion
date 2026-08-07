"""Immutable contracts for future reliability analysis and protection planning.

These values describe analysis inputs and planned outputs before allocation. They do
not simulate noise, select an error-correcting code, or expose physical realization
details through a source-level ``Qubit``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite

from ariadion_core import canonical_json, require_nonempty_identifier

from .executable_noise import ExecutableNoiseModel


class EvolutionModel(str, Enum):
    """The numerical evolution representation requested of a future simulator."""

    STATE_VECTOR = "state_vector"
    DENSITY_MATRIX = "density_matrix"
    STOCHASTIC_TRAJECTORIES = "stochastic_trajectories"
    STABILIZER = "stabilizer"


class NoiseModelOrigin(str, Enum):
    """Where a future request expects its noise assumptions to originate."""

    NONE = "none"
    DECLARED = "declared"
    DEVICE_PROFILE = "device_profile"


class NoiseFeature(str, Enum):
    """An independently selected feature of a future noise model."""

    GATE_CHANNELS = "gate_channels"
    IDLE_DECOHERENCE = "idle_decoherence"
    READOUT_ERRORS = "readout_errors"
    LEAKAGE = "leakage"
    CORRELATIONS = "correlations"


class ProtectionStrategy(str, Enum):
    """The realization category chosen by a future protection planner."""

    BARE = "bare"
    MITIGATED = "mitigated"
    ERROR_DETECTED = "error_detected"
    FAULT_TOLERANT = "fault_tolerant"


@dataclass(frozen=True, slots=True)
class ReliabilityGoal:
    """A requested upper bound on total failure probability.

    ``confidence`` describes confidence in a future estimate, not a second failure
    budget. A goal does not prescribe physical-qubit counts or code distance.
    """

    maximum_failure_probability: float
    confidence: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "maximum_failure_probability",
            _normalize_probability(
                self.maximum_failure_probability,
                label="maximum failure probability",
                strictly_positive=True,
            ),
        )
        if self.confidence is not None:
            object.__setattr__(
                self,
                "confidence",
                _normalize_probability(self.confidence, label="reliability confidence"),
            )

    def to_dict(self) -> dict[str, float | None]:
        return {
            "maximum_failure_probability": self.maximum_failure_probability,
            "confidence": self.confidence,
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class GateNoise:
    """One named gate-channel error assumption in a noise profile.

    The operation and channel names are descriptive identifiers. They do not bind
    source-level ``Qubit`` values to backend targets or execute a channel.
    """

    operation: str
    channel: str
    error_probability: float
    duration_ns: float | None = None

    def __post_init__(self) -> None:
        require_nonempty_identifier(self.operation, label="gate noise operation")
        require_nonempty_identifier(self.channel, label="gate noise channel")
        object.__setattr__(
            self,
            "error_probability",
            _normalize_probability(self.error_probability, label="gate noise error probability"),
        )
        if self.duration_ns is not None:
            object.__setattr__(
                self,
                "duration_ns",
                _normalize_nonnegative_number(self.duration_ns, label="gate noise duration_ns"),
            )

    def to_dict(self) -> dict[str, str | float | None]:
        return {
            "operation": self.operation,
            "channel": self.channel,
            "error_probability": self.error_probability,
            "duration_ns": self.duration_ns,
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class IdleNoise:
    """T1/T2 time constants used after a future schedule determines idle time."""

    t1_ns: float | None = None
    t2_ns: float | None = None

    def __post_init__(self) -> None:
        if self.t1_ns is None and self.t2_ns is None:
            raise ValueError("idle noise requires t1_ns or t2_ns")
        t1_ns = (
            _normalize_positive_number(self.t1_ns, label="idle noise t1_ns")
            if self.t1_ns is not None
            else None
        )
        t2_ns = (
            _normalize_positive_number(self.t2_ns, label="idle noise t2_ns")
            if self.t2_ns is not None
            else None
        )
        if t1_ns is not None and t2_ns is not None and t2_ns > 2 * t1_ns:
            raise ValueError("idle noise t2_ns must be less than or equal to 2 * t1_ns")
        object.__setattr__(self, "t1_ns", t1_ns)
        object.__setattr__(self, "t2_ns", t2_ns)

    def to_dict(self) -> dict[str, float | None]:
        return {"t1_ns": self.t1_ns, "t2_ns": self.t2_ns}

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class ReadoutNoise:
    """A readout-error assumption kept separate from gate-channel errors."""

    error_probability: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "error_probability",
            _normalize_probability(self.error_probability, label="readout error probability"),
        )

    def to_dict(self) -> dict[str, float]:
        return {"error_probability": self.error_probability}

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class LeakageModel:
    """A leakage-event assumption distinct from ordinary computational noise."""

    leakage_probability: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "leakage_probability",
            _normalize_probability(self.leakage_probability, label="leakage probability"),
        )

    def to_dict(self) -> dict[str, float]:
        return {"leakage_probability": self.leakage_probability}

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class CorrelationModel:
    """A named correlated-event assumption outside independent channel noise."""

    name: str
    event_probability: float

    def __post_init__(self) -> None:
        require_nonempty_identifier(self.name, label="correlation model name")
        object.__setattr__(
            self,
            "event_probability",
            _normalize_probability(
                self.event_probability,
                label="correlation event probability",
            ),
        )

    def to_dict(self) -> dict[str, str | float]:
        return {"name": self.name, "event_probability": self.event_probability}

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class NoiseProfile:
    """A layered collection of future noise-model assumptions.

    A profile separates individual gate channels from time-dependent idle noise,
    readout error, leakage, and correlated events. It is descriptive only; a future
    simulator or estimator decides how each component is evaluated.
    """

    gate_channels: tuple[GateNoise, ...] = ()
    idle_noise: IdleNoise | None = None
    readout_noise: ReadoutNoise | None = None
    leakage: LeakageModel | None = None
    correlations: CorrelationModel | None = None

    def __post_init__(self) -> None:
        _require_tuple(self.gate_channels, label="noise profile gate_channels")
        if not all(isinstance(channel, GateNoise) for channel in self.gate_channels):
            raise ValueError("noise profile gate_channels must contain GateNoise values")
        _require_optional_type(self.idle_noise, IdleNoise, label="noise profile idle_noise")
        _require_optional_type(
            self.readout_noise,
            ReadoutNoise,
            label="noise profile readout_noise",
        )
        _require_optional_type(self.leakage, LeakageModel, label="noise profile leakage")
        _require_optional_type(
            self.correlations,
            CorrelationModel,
            label="noise profile correlations",
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "gate_channels": [channel.to_dict() for channel in self.gate_channels],
            "idle_noise": self.idle_noise.to_dict() if self.idle_noise is not None else None,
            "readout_noise": (
                self.readout_noise.to_dict() if self.readout_noise is not None else None
            ),
            "leakage": self.leakage.to_dict() if self.leakage is not None else None,
            "correlations": (
                self.correlations.to_dict() if self.correlations is not None else None
            ),
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class ProtectionPlan:
    """A future planner's descriptive realization choice for one compiled program.

    This contract records a selected plan and its assumptions. It neither chooses a
    code distance nor maps a source-level ``Qubit`` to physical qubits.
    """

    strategy: ProtectionStrategy
    code_name: str | None
    code_distance: int | None
    estimated_failure_probability: float
    physical_qubit_count: int
    assumptions: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.strategy, ProtectionStrategy):
            raise ValueError("protection plan strategy must be a ProtectionStrategy")
        if self.code_name is not None:
            require_nonempty_identifier(self.code_name, label="protection plan code_name")
        if self.code_distance is not None and (
            isinstance(self.code_distance, bool)
            or not isinstance(self.code_distance, int)
            or self.code_distance < 1
        ):
            raise ValueError("protection plan code_distance must be a positive integer")
        if self.strategy is ProtectionStrategy.BARE and (
            self.code_name is not None or self.code_distance is not None
        ):
            raise ValueError("bare protection plans cannot specify a code name or code distance")
        if self.strategy is ProtectionStrategy.MITIGATED and self.code_distance is not None:
            raise ValueError("mitigated protection plans cannot specify a code distance")
        if (
            self.strategy
            in {ProtectionStrategy.ERROR_DETECTED, ProtectionStrategy.FAULT_TOLERANT}
            and self.code_name is None
        ):
            raise ValueError(
                "error-detected and fault-tolerant protection plans require a code name"
            )
        object.__setattr__(
            self,
            "estimated_failure_probability",
            _normalize_probability(
                self.estimated_failure_probability,
                label="estimated failure probability",
            ),
        )
        if (
            isinstance(self.physical_qubit_count, bool)
            or not isinstance(self.physical_qubit_count, int)
            or self.physical_qubit_count < 0
        ):
            raise ValueError("protection plan physical_qubit_count must be a non-negative integer")
        _require_tuple(self.assumptions, label="protection plan assumptions")
        for assumption in self.assumptions:
            require_nonempty_identifier(assumption, label="protection plan assumption")

    def to_dict(self) -> dict[str, object]:
        return {
            "strategy": self.strategy.value,
            "code_name": self.code_name,
            "code_distance": self.code_distance,
            "estimated_failure_probability": self.estimated_failure_probability,
            "physical_qubit_count": self.physical_qubit_count,
            "assumptions": list(self.assumptions),
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class SimulationRequest:
    """Composable simulator intent with explicit noise-model provenance.

    Numerical evolution, noise provenance, noise features, and a protected
    realization remain independent dimensions. Declared noise must name either a
    typed executable model or a non-empty reference; ``NONE`` carries neither.
    This request does not run simulation or imply that an engine for every
    combination exists.
    """

    evolution_model: EvolutionModel
    noise_model_origin: NoiseModelOrigin
    noise_features: tuple[NoiseFeature, ...] = ()
    protection_plan: ProtectionPlan | None = None
    noise_model: ExecutableNoiseModel | None = None
    noise_model_reference: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.evolution_model, EvolutionModel):
            raise ValueError("simulation request evolution_model must be an EvolutionModel")
        if not isinstance(self.noise_model_origin, NoiseModelOrigin):
            raise ValueError(
                "simulation request noise_model_origin must be a NoiseModelOrigin"
            )
        _require_tuple(self.noise_features, label="simulation request noise_features")
        if not all(isinstance(feature, NoiseFeature) for feature in self.noise_features):
            raise ValueError("simulation request noise_features must contain NoiseFeature values")
        if len(self.noise_features) != len(set(self.noise_features)):
            raise ValueError("simulation request noise_features must be unique")
        if self.noise_model is not None and not isinstance(
            self.noise_model,
            ExecutableNoiseModel,
        ):
            raise ValueError("simulation request noise_model must be ExecutableNoiseModel")
        if self.noise_model_reference is not None:
            require_nonempty_identifier(
                self.noise_model_reference,
                label="simulation request noise_model_reference",
            )
        if self.noise_model_origin is NoiseModelOrigin.NONE:
            if self.noise_features:
                raise ValueError("noise model origin NONE cannot select noise features")
            if self.noise_model is not None or self.noise_model_reference is not None:
                raise ValueError("noise model origin NONE cannot carry a noise model")
        elif self.noise_model_origin is NoiseModelOrigin.DECLARED and (
            self.noise_model is None and self.noise_model_reference is None
        ):
            raise ValueError(
                "noise model origin DECLARED requires a noise_model or noise_model_reference"
            )
        elif self.noise_model_origin is NoiseModelOrigin.DEVICE_PROFILE and (
            self.noise_model_reference is None
        ):
            raise ValueError(
                "noise model origin DEVICE_PROFILE requires a noise_model_reference"
            )
        if self.protection_plan is not None and not isinstance(
            self.protection_plan,
            ProtectionPlan,
        ):
            raise ValueError("simulation request protection_plan must be ProtectionPlan")

    def to_dict(self) -> dict[str, object]:
        return {
            "evolution_model": self.evolution_model.value,
            "noise_model_origin": self.noise_model_origin.value,
            "noise_features": [feature.value for feature in self.noise_features],
            "noise_model": (
                self.noise_model.to_dict() if self.noise_model is not None else None
            ),
            "noise_model_reference": self.noise_model_reference,
            "protection_plan": (
                self.protection_plan.to_dict() if self.protection_plan is not None else None
            ),
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


def _normalize_probability(
    value: object,
    *,
    label: str,
    strictly_positive: bool = False,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be numeric")
    probability = float(value)
    if not isfinite(probability):
        raise ValueError(f"{label} must be finite")
    if probability < 0 or probability > 1 or (strictly_positive and probability == 0):
        expected = "in (0, 1]" if strictly_positive else "in [0, 1]"
        raise ValueError(f"{label} must be {expected}")
    return probability


def _normalize_nonnegative_number(value: object, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be numeric")
    number = float(value)
    if not isfinite(number) or number < 0:
        raise ValueError(f"{label} must be a finite non-negative number")
    return number


def _normalize_positive_number(value: object, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be numeric")
    number = float(value)
    if not isfinite(number) or number <= 0:
        raise ValueError(f"{label} must be a finite positive number")
    return number


def _require_tuple(value: object, *, label: str) -> None:
    if not isinstance(value, tuple):
        raise ValueError(f"{label} must be a tuple")


def _require_optional_type(value: object, expected_type: type[object], *, label: str) -> None:
    if value is not None and not isinstance(value, expected_type):
        raise ValueError(f"{label} must be {expected_type.__name__} when provided")


__all__ = [
    "CorrelationModel",
    "EvolutionModel",
    "GateNoise",
    "IdleNoise",
    "LeakageModel",
    "NoiseFeature",
    "NoiseModelOrigin",
    "NoiseProfile",
    "ProtectionPlan",
    "ProtectionStrategy",
    "ReadoutNoise",
    "ReliabilityGoal",
    "SimulationRequest",
]
