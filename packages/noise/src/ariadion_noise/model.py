"""Provider-neutral executable quantum-noise channel contracts.

These immutable values deliberately do not depend on source semantics or allocated
IR. A future execution backend resolves ``OneQubitGate`` values to its own lowered
operations before applying the mathematical channels defined here.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from math import isclose, isfinite, sqrt
from typing import ClassVar, TypeAlias

from ariadion_core import canonical_json, require_nonempty_identifier


KRAUS_COMPLETENESS_ABS_TOLERANCE = 1e-12

# Each nested tuple is indexed as ``operator[row][column]`` in computational-basis order.
KrausOperator: TypeAlias = tuple[tuple[complex, complex], tuple[complex, complex]]
KrausOperators: TypeAlias = tuple[KrausOperator, ...]


class NoiseFeature(str, Enum):
    """Executable and descriptive noise capabilities tracked independently."""

    GATE_CHANNELS = "gate_channels"
    IDLE_DECOHERENCE = "idle_decoherence"
    READOUT_ERRORS = "readout_errors"
    LEAKAGE = "leakage"
    CORRELATIONS = "correlations"


class OneQubitGate(str, Enum):
    """Public one-qubit gate categories supported by the first channel model."""

    X = "x"
    H = "h"
    Z = "z"
    RX = "rx"
    RY = "ry"
    RZ = "rz"


class QuantumChannelValidationError(ValueError):
    """Raised when a custom one-qubit Kraus channel is not executable."""


class QuantumChannel(ABC):
    r"""A provider-neutral one-qubit channel represented by Kraus operators.

    The ordered operators define
    $\mathcal{E}(\rho) = \sum_k K_k \rho K_k^\dagger$. A simulator validates
    their shape, finite entries, and completeness before execution.
    """

    __slots__ = ()

    qubit_count: ClassVar[int] = 1

    @abstractmethod
    def kraus_operators(self) -> KrausOperators:
        """Return this channel's ordered Kraus operators."""

    @abstractmethod
    def to_dict(self) -> dict[str, object]:
        """Return a deterministic, JSON-compatible channel description."""

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class BitFlipChannel(QuantumChannel):
    """Apply $X$ with probability ``probability`` and identity otherwise."""

    probability: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "probability",
            _normalize_probability(self.probability, label="bit-flip probability"),
        )

    def kraus_operators(self) -> KrausOperators:
        identity_scale = sqrt(1 - self.probability)
        flip_scale = sqrt(self.probability)
        return (
            ((identity_scale + 0j, 0j), (0j, identity_scale + 0j)),
            ((0j, flip_scale + 0j), (flip_scale + 0j, 0j)),
        )

    def to_dict(self) -> dict[str, object]:
        return {"kind": "bit_flip", "probability": self.probability}


@dataclass(frozen=True, slots=True)
class PhaseFlipChannel(QuantumChannel):
    """Apply $Z$ with probability ``probability`` and identity otherwise."""

    probability: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "probability",
            _normalize_probability(self.probability, label="phase-flip probability"),
        )

    def kraus_operators(self) -> KrausOperators:
        identity_scale = sqrt(1 - self.probability)
        flip_scale = sqrt(self.probability)
        return (
            ((identity_scale + 0j, 0j), (0j, identity_scale + 0j)),
            ((flip_scale + 0j, 0j), (0j, -flip_scale + 0j)),
        )

    def to_dict(self) -> dict[str, object]:
        return {"kind": "phase_flip", "probability": self.probability}


@dataclass(frozen=True, slots=True)
class DepolarizingChannel(QuantumChannel):
    """Apply $I$, $X$, $Y$, or $Z$ with probabilities $1-p$, $p/3$, $p/3$, $p/3$."""

    probability: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "probability",
            _normalize_probability(self.probability, label="depolarizing probability"),
        )

    def kraus_operators(self) -> KrausOperators:
        identity_scale = sqrt(1 - self.probability)
        pauli_scale = sqrt(self.probability / 3)
        return (
            ((identity_scale + 0j, 0j), (0j, identity_scale + 0j)),
            ((0j, pauli_scale + 0j), (pauli_scale + 0j, 0j)),
            ((0j, -1j * pauli_scale), (1j * pauli_scale, 0j)),
            ((pauli_scale + 0j, 0j), (0j, -pauli_scale + 0j)),
        )

    def to_dict(self) -> dict[str, object]:
        return {"kind": "depolarizing", "probability": self.probability}


@dataclass(frozen=True, slots=True)
class AmplitudeDampingChannel(QuantumChannel):
    r"""Damp $|1\rangle$ to $|0\rangle$ with probability ``probability``."""

    probability: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "probability",
            _normalize_probability(
                self.probability,
                label="amplitude-damping probability",
            ),
        )

    def kraus_operators(self) -> KrausOperators:
        retained_scale = sqrt(1 - self.probability)
        damping_scale = sqrt(self.probability)
        return (
            ((1 + 0j, 0j), (0j, retained_scale + 0j)),
            ((0j, damping_scale + 0j), (0j, 0j)),
        )

    def to_dict(self) -> dict[str, object]:
        return {"kind": "amplitude_damping", "probability": self.probability}


@dataclass(frozen=True, slots=True)
class PhaseDampingChannel(QuantumChannel):
    """Damp coherences with the explicit two-Kraus ``probability`` convention."""

    probability: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "probability",
            _normalize_probability(self.probability, label="phase-damping probability"),
        )

    def kraus_operators(self) -> KrausOperators:
        retained_scale = sqrt(1 - self.probability)
        damping_scale = sqrt(self.probability)
        return (
            ((1 + 0j, 0j), (0j, retained_scale + 0j)),
            ((0j, 0j), (0j, damping_scale + 0j)),
        )

    def to_dict(self) -> dict[str, object]:
        return {"kind": "phase_damping", "probability": self.probability}


@dataclass(frozen=True, slots=True)
class BinaryReadoutChannel:
    r"""A classical binary readout channel with independent directional errors.

    ``p_one_given_zero`` is $P(\widetilde{b}=1\mid b=0)$ and
    ``p_zero_given_one`` is $P(\widetilde{b}=0\mid b=1)$. It changes reported
    outcomes after physical measurement; it is never a quantum gate channel.
    """

    p_one_given_zero: float
    p_zero_given_one: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "p_one_given_zero",
            _normalize_probability(
                self.p_one_given_zero,
                label="readout p_one_given_zero",
            ),
        )
        object.__setattr__(
            self,
            "p_zero_given_one",
            _normalize_probability(
                self.p_zero_given_one,
                label="readout p_zero_given_one",
            ),
        )

    def probability(self, observed_bit: int, actual_bit: int) -> float:
        r"""Return $P(\widetilde{b}=observed\_bit\mid b=actual\_bit)$."""

        _require_binary_bit(observed_bit, label="observed_bit")
        _require_binary_bit(actual_bit, label="actual_bit")
        if actual_bit == 0:
            return self.p_one_given_zero if observed_bit == 1 else 1 - self.p_one_given_zero
        return self.p_zero_given_one if observed_bit == 0 else 1 - self.p_zero_given_one

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": "binary_readout",
            "p_one_given_zero": self.p_one_given_zero,
            "p_zero_given_one": self.p_zero_given_one,
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class GateChannelBinding:
    """Bind a typed one-qubit channel to a neutral public gate category."""

    gate: OneQubitGate
    channel: QuantumChannel

    def __post_init__(self) -> None:
        if not isinstance(self.gate, OneQubitGate):
            raise ValueError("gate channel binding gate must be a OneQubitGate")
        if not isinstance(self.channel, QuantumChannel):
            raise ValueError("gate channel binding channel must be a QuantumChannel")
        if self.channel.qubit_count != 1:
            raise ValueError("gate channel bindings require single-qubit channels")

    def to_dict(self) -> dict[str, object]:
        return {"gate": self.gate.value, "channel": self.channel.to_dict()}

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class ExecutableNoiseModel:
    """Typed provider-neutral channels for a future noisy execution backend.

    Gate channels are keyed by public single-qubit gate categories. A configured
    binary readout channel applies independently to each distinct terminal
    observation; runtime maps this neutral model to allocated operations.
    """

    gate_channels: tuple[GateChannelBinding, ...] = ()
    readout_channel: BinaryReadoutChannel | None = None

    def __post_init__(self) -> None:
        _require_tuple(self.gate_channels, label="executable noise model gate_channels")
        if not all(isinstance(binding, GateChannelBinding) for binding in self.gate_channels):
            raise ValueError(
                "executable noise model gate_channels must contain GateChannelBinding values"
            )
        gates = tuple(binding.gate for binding in self.gate_channels)
        if len(gates) != len(set(gates)):
            raise ValueError("executable noise model gate channel bindings must be unique")
        if self.readout_channel is not None and not isinstance(
            self.readout_channel,
            BinaryReadoutChannel,
        ):
            raise ValueError(
                "executable noise model readout_channel must be BinaryReadoutChannel"
            )
        object.__setattr__(
            self,
            "gate_channels",
            tuple(sorted(self.gate_channels, key=lambda binding: binding.gate.value)),
        )

    @property
    def features(self) -> tuple[NoiseFeature, ...]:
        features: list[NoiseFeature] = []
        if self.gate_channels:
            features.append(NoiseFeature.GATE_CHANNELS)
        if self.readout_channel is not None:
            features.append(NoiseFeature.READOUT_ERRORS)
        return tuple(features)

    def channel_for_gate(self, gate: OneQubitGate) -> QuantumChannel | None:
        for binding in self.gate_channels:
            if binding.gate is gate:
                return binding.channel
        return None

    def to_dict(self) -> dict[str, object]:
        return {
            "gate_channels": [binding.to_dict() for binding in self.gate_channels],
            "readout_channel": (
                self.readout_channel.to_dict() if self.readout_channel is not None else None
            ),
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class NoiseBindingResult:
    """Inspectable executable binding evidence with explicit unsupported features."""

    model: ExecutableNoiseModel
    assumptions: tuple[str, ...] = ()
    unsupported_features: tuple[NoiseFeature, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.model, ExecutableNoiseModel):
            raise ValueError("noise binding result model must be an ExecutableNoiseModel")
        _require_tuple(self.assumptions, label="noise binding result assumptions")
        for assumption in self.assumptions:
            require_nonempty_identifier(assumption, label="noise binding assumption")
        _require_tuple(
            self.unsupported_features,
            label="noise binding result unsupported_features",
        )
        if not all(isinstance(feature, NoiseFeature) for feature in self.unsupported_features):
            raise ValueError(
                "noise binding result unsupported_features must contain NoiseFeature values"
            )
        if len(self.unsupported_features) != len(set(self.unsupported_features)):
            raise ValueError("noise binding result unsupported_features must be unique")
        feature_order = {feature: index for index, feature in enumerate(NoiseFeature)}
        object.__setattr__(
            self,
            "unsupported_features",
            tuple(sorted(self.unsupported_features, key=feature_order.__getitem__)),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "model": self.model.to_dict(),
            "assumptions": list(self.assumptions),
            "unsupported_features": [feature.value for feature in self.unsupported_features],
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class IdleDecoherenceProfile:
    """T1/T2 time constants for executable idle-decoherence channel calculation.

    At least one of ``t1_ns`` and ``t2_ns`` must be supplied. When both are
    given, ``t2_ns`` must satisfy ``t2_ns <= 2 * t1_ns``; a larger value would
    imply a negative pure-dephasing rate, which is unphysical.

    Behavior by supplied constants:

    * Only T1 given: amplitude-damping channel only; no additional pure-dephasing
      channel is applied.
    * Only T2 given: pure phase-damping only; no population loss.
    * Both given: amplitude damping at rate T1 plus additional phase damping chosen
      so the total coherence decay equals ``exp(-t / t2_ns)``.

    Zero idle duration always produces identity evolution regardless of which
    constants are supplied.
    """

    t1_ns: float | None = None
    t2_ns: float | None = None

    def __post_init__(self) -> None:
        if self.t1_ns is None and self.t2_ns is None:
            raise ValueError("idle decoherence profile requires t1_ns or t2_ns")
        t1 = (
            _normalize_positive_number(self.t1_ns, label="idle decoherence profile t1_ns")
            if self.t1_ns is not None
            else None
        )
        t2 = (
            _normalize_positive_number(self.t2_ns, label="idle decoherence profile t2_ns")
            if self.t2_ns is not None
            else None
        )
        if t1 is not None and t2 is not None and t2 > 2 * t1:
            raise ValueError(
                "idle decoherence profile t2_ns must be less than or equal to 2 * t1_ns"
            )
        object.__setattr__(self, "t1_ns", t1)
        object.__setattr__(self, "t2_ns", t2)

    def to_dict(self) -> dict[str, float | None]:
        return {"t1_ns": self.t1_ns, "t2_ns": self.t2_ns}

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


def validate_quantum_channel(channel: QuantumChannel) -> KrausOperators:
    """Validate and return one executable one-qubit Kraus channel.

    This deliberately validates runtime behavior instead of trusting a custom
    ``QuantumChannel`` implementation's annotations or serialization metadata.
    """

    if not isinstance(channel, QuantumChannel):
        raise QuantumChannelValidationError("quantum channel must be a QuantumChannel")
    if channel.qubit_count != 1:
        raise QuantumChannelValidationError("only one-qubit quantum channels are supported")
    operators = channel.kraus_operators()
    if not isinstance(operators, tuple) or not operators:
        raise QuantumChannelValidationError("quantum channel Kraus operators must be non-empty")
    for operator in operators:
        if not isinstance(operator, tuple) or len(operator) != 2:
            raise QuantumChannelValidationError("quantum channel Kraus operators must be 2x2")
        for row in operator:
            if not isinstance(row, tuple) or len(row) != 2:
                raise QuantumChannelValidationError("quantum channel Kraus operators must be 2x2")
            for value in row:
                if not isinstance(value, complex) or not (
                    isfinite(value.real) and isfinite(value.imag)
                ):
                    raise QuantumChannelValidationError(
                        "quantum channel Kraus entries must be finite complex values"
                    )

    completeness = [[0j, 0j], [0j, 0j]]
    for operator in operators:
        for row in range(2):
            for column in range(2):
                completeness[row][column] += sum(
                    operator[index][row].conjugate() * operator[index][column]
                    for index in range(2)
                )
    for row in range(2):
        for column in range(2):
            expected = 1 if row == column else 0
            if not isclose(
                completeness[row][column].real,
                expected,
                rel_tol=0.0,
                abs_tol=KRAUS_COMPLETENESS_ABS_TOLERANCE,
            ) or not isclose(
                completeness[row][column].imag,
                0.0,
                rel_tol=0.0,
                abs_tol=KRAUS_COMPLETENESS_ABS_TOLERANCE,
            ):
                raise QuantumChannelValidationError(
                    "quantum channel Kraus operators must satisfy sum(K†K) = I"
                )
    return operators


def validate_executable_noise_model(model: ExecutableNoiseModel) -> None:
    """Validate every configured channel before a backend applies the model."""

    if not isinstance(model, ExecutableNoiseModel):
        raise ValueError("executable noise model must be an ExecutableNoiseModel")
    for binding in model.gate_channels:
        validate_quantum_channel(binding.channel)


def _normalize_probability(value: object, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be numeric")
    probability = float(value)
    if not isfinite(probability):
        raise ValueError(f"{label} must be finite")
    if probability < 0 or probability > 1:
        raise ValueError(f"{label} must be in [0, 1]")
    return probability


def _normalize_positive_number(value: object, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be numeric")
    number = float(value)
    if not isfinite(number):
        raise ValueError(f"{label} must be finite")
    if number <= 0:
        raise ValueError(f"{label} must be positive")
    return number


def _require_binary_bit(value: object, *, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value not in {0, 1}:
        raise ValueError(f"{label} must be an integer bit")


def _require_tuple(value: object, *, label: str) -> None:
    if not isinstance(value, tuple):
        raise ValueError(f"{label} must be a tuple")


__all__ = [
    "AmplitudeDampingChannel",
    "BinaryReadoutChannel",
    "BitFlipChannel",
    "DepolarizingChannel",
    "ExecutableNoiseModel",
    "GateChannelBinding",
    "IdleDecoherenceProfile",
    "KRAUS_COMPLETENESS_ABS_TOLERANCE",
    "KrausOperator",
    "KrausOperators",
    "NoiseBindingResult",
    "NoiseFeature",
    "OneQubitGate",
    "PhaseDampingChannel",
    "PhaseFlipChannel",
    "QuantumChannel",
    "QuantumChannelValidationError",
    "validate_executable_noise_model",
    "validate_quantum_channel",
]