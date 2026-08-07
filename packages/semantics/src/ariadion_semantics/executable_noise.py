"""Provider-neutral executable quantum-noise channel contracts.

These immutable values are intentionally distinct from ``NoiseProfile``. A
profile describes planning assumptions, while this module defines small,
mathematically specified channels that a future noisy simulator can apply after
lowering. Defining Kraus operators here does not add density-matrix evolution to
the current state-vector simulator.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from math import isfinite, sqrt
from typing import TYPE_CHECKING, ClassVar, TypeAlias

from ariadion_core import canonical_json, require_nonempty_identifier
from ariadion_ir import OpCode

if TYPE_CHECKING:
    from .reliability import NoiseFeature


# Each nested tuple is indexed as ``operator[row][column]`` in computational basis order.
KrausOperator: TypeAlias = tuple[tuple[complex, complex], tuple[complex, complex]]
KrausOperators: TypeAlias = tuple[KrausOperator, ...]

_SINGLE_QUBIT_GATE_OPCODES = frozenset(
    {
        OpCode.X,
        OpCode.H,
        OpCode.Z,
        OpCode.RX,
        OpCode.RY,
        OpCode.RZ,
    }
)


class QuantumChannel(ABC):
    r"""A provider-neutral quantum channel represented by Kraus operators.

    The operators define $\mathcal{E}(\rho) = \sum_k K_k\rho K_k^\dagger$.
    They are channel data only: applying them remains the responsibility of a
    future density-matrix or trajectory backend.
    """

    __slots__ = ()

    qubit_count: ClassVar[int] = 1

    @abstractmethod
    def kraus_operators(self) -> KrausOperators:
        """Return the channel's ordered, trace-preserving Kraus operators."""

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
    ``p_zero_given_one`` is $P(\widetilde{b}=0\mid b=1)$. This channel changes
    recorded outcomes after observation; it is not a quantum gate channel.
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
    """Bind one single-qubit executable channel to a lowered single-qubit gate opcode."""

    opcode: OpCode
    channel: QuantumChannel

    def __post_init__(self) -> None:
        if not isinstance(self.opcode, OpCode):
            raise ValueError("gate channel binding opcode must be an OpCode")
        if self.opcode not in _SINGLE_QUBIT_GATE_OPCODES:
            raise ValueError(
                "gate channel bindings support only single-qubit gate opcodes; "
                "multi-qubit, measurement, and reset opcodes are unsupported"
            )
        if not isinstance(self.channel, QuantumChannel):
            raise ValueError("gate channel binding channel must be a QuantumChannel")
        if self.channel.qubit_count != 1:
            raise ValueError("gate channel bindings require single-qubit channels")

    def to_dict(self) -> dict[str, object]:
        return {"opcode": self.opcode.value, "channel": self.channel.to_dict()}

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class ReadoutChannelBinding:
    """Bind a classical readout channel to lowered ``MEASURE`` operations."""

    opcode: OpCode
    channel: BinaryReadoutChannel

    def __post_init__(self) -> None:
        if not isinstance(self.opcode, OpCode):
            raise ValueError("readout channel binding opcode must be an OpCode")
        if self.opcode is not OpCode.MEASURE:
            raise ValueError("readout channel bindings require the MEASURE opcode")
        if not isinstance(self.channel, BinaryReadoutChannel):
            raise ValueError(
                "readout channel binding channel must be a BinaryReadoutChannel"
            )

    def to_dict(self) -> dict[str, object]:
        return {"opcode": self.opcode.value, "channel": self.channel.to_dict()}

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class ExecutableNoiseModel:
    """Typed executable channel bindings for a future noisy simulator.

    Bindings are keyed by lowered ``OpCode`` values, never by Python source
    spelling. The current model supports only single-qubit gate channels and
    classical readout channels; it intentionally has no two-qubit, leakage,
    correlated, or timing-derived idle channel representation.
    """

    gate_channels: tuple[GateChannelBinding, ...] = ()
    readout_channels: tuple[ReadoutChannelBinding, ...] = ()

    def __post_init__(self) -> None:
        _require_tuple(self.gate_channels, label="executable noise model gate_channels")
        _require_tuple(
            self.readout_channels,
            label="executable noise model readout_channels",
        )
        if not all(isinstance(binding, GateChannelBinding) for binding in self.gate_channels):
            raise ValueError(
                "executable noise model gate_channels must contain GateChannelBinding values"
            )
        if not all(
            isinstance(binding, ReadoutChannelBinding) for binding in self.readout_channels
        ):
            raise ValueError(
                "executable noise model readout_channels must contain "
                "ReadoutChannelBinding values"
            )
        _require_unique_opcodes(self.gate_channels, label="gate")
        _require_unique_opcodes(self.readout_channels, label="readout")
        object.__setattr__(
            self,
            "gate_channels",
            tuple(sorted(self.gate_channels, key=lambda binding: binding.opcode.value)),
        )
        object.__setattr__(
            self,
            "readout_channels",
            tuple(sorted(self.readout_channels, key=lambda binding: binding.opcode.value)),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "gate_channels": [binding.to_dict() for binding in self.gate_channels],
            "readout_channels": [binding.to_dict() for binding in self.readout_channels],
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class NoiseBindingResult:
    """Inspectable executable binding evidence with explicit unsupported features.

    A compiler or runtime can retain this result beside an execution request. It
    records assumptions and every unsupported descriptive feature rather than
    silently treating omitted features as executable channels.
    """

    model: ExecutableNoiseModel
    assumptions: tuple[str, ...] = ()
    unsupported_features: tuple[NoiseFeature, ...] = ()

    def __post_init__(self) -> None:
        from .reliability import NoiseFeature

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


def _normalize_probability(value: object, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be numeric")
    probability = float(value)
    if not isfinite(probability):
        raise ValueError(f"{label} must be finite")
    if probability < 0 or probability > 1:
        raise ValueError(f"{label} must be in [0, 1]")
    return probability


def _require_binary_bit(value: object, *, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value not in {0, 1}:
        raise ValueError(f"{label} must be an integer bit")


def _require_tuple(value: object, *, label: str) -> None:
    if not isinstance(value, tuple):
        raise ValueError(f"{label} must be a tuple")


def _require_unique_opcodes(
    bindings: tuple[GateChannelBinding, ...] | tuple[ReadoutChannelBinding, ...],
    *,
    label: str,
) -> None:
    opcodes = tuple(binding.opcode for binding in bindings)
    if len(opcodes) != len(set(opcodes)):
        raise ValueError(f"executable noise model {label} channel bindings must be unique")


__all__ = [
    "AmplitudeDampingChannel",
    "BinaryReadoutChannel",
    "BitFlipChannel",
    "DepolarizingChannel",
    "ExecutableNoiseModel",
    "GateChannelBinding",
    "KrausOperator",
    "KrausOperators",
    "NoiseBindingResult",
    "PhaseDampingChannel",
    "PhaseFlipChannel",
    "QuantumChannel",
    "ReadoutChannelBinding",
]
