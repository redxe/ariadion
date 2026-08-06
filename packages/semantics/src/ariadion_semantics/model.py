from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ariadion_core import (
    LogicalOperationId,
    LogicalQubitId,
    SourceRef,
    canonical_json,
    require_nonempty_identifier,
)


class FunctionEffect(str, Enum):
    """The reserved effect categories for future source-function analysis."""

    CLASSICAL = "classical"
    QUANTUM = "quantum"
    HYBRID = "hybrid"


class LogicalOpCode(str, Enum):
    """Pre-allocation operations over logical quantum identities."""

    X = "x"
    H = "h"
    Z = "z"
    RX = "rx"
    RY = "ry"
    RZ = "rz"
    CX = "cx"


class ObservationReason(str, Enum):
    """Why a logical quantum value becomes a classical observation."""

    EXPLICIT = "explicit"
    CLASSICAL_RETURN = "classical_return"
    CLASSICAL_ASSIGNMENT = "classical_assignment"
    BRANCH_CONDITION = "branch_condition"
    PROGRAM_OUTPUT = "program_output"


@dataclass(frozen=True, slots=True)
class Basis:
    """A semantic basis descriptor whose name may later bind to a custom basis."""

    name: str

    def __post_init__(self) -> None:
        require_nonempty_identifier(self.name, label="basis name")

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name}

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class LogicalQubitValue:
    """A resolved logical quantum value before lifetime analysis or allocation."""

    id: LogicalQubitId
    display_name: str | None = None
    source: SourceRef | None = None

    def __post_init__(self) -> None:
        require_nonempty_identifier(self.id, label="logical qubit ID")
        if self.display_name is not None:
            require_nonempty_identifier(self.display_name, label="logical qubit display name")
        if self.source is not None and not isinstance(self.source, SourceRef):
            raise ValueError("logical qubit source must be SourceRef")

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "source": self.source.to_dict() if self.source is not None else None,
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class LogicalOperation:
    """A pre-allocation operation targeting logical identities rather than slots."""

    id: LogicalOperationId
    opcode: LogicalOpCode
    targets: tuple[LogicalQubitId, ...]
    controls: tuple[LogicalQubitId, ...] = ()
    source: SourceRef | None = None

    def __post_init__(self) -> None:
        require_nonempty_identifier(self.id, label="logical operation ID")
        if not isinstance(self.opcode, LogicalOpCode):
            raise ValueError("logical operation opcode must be LogicalOpCode")
        _validate_logical_qubit_ids(self.targets, label="logical operation targets")
        _validate_logical_qubit_ids(
            self.controls,
            label="logical operation controls",
            allow_empty=True,
        )
        if self.source is not None and not isinstance(self.source, SourceRef):
            raise ValueError("logical operation source must be SourceRef")

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "opcode": self.opcode.value,
            "targets": list(self.targets),
            "controls": list(self.controls),
            "source": self.source.to_dict() if self.source is not None else None,
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class Observation:
    """A semantic observation boundary that Daidalon will later lower to MEASURE."""

    qubit_id: LogicalQubitId
    basis: Basis
    reason: ObservationReason
    source: SourceRef | None = None

    def __post_init__(self) -> None:
        require_nonempty_identifier(self.qubit_id, label="observed logical qubit ID")
        if not isinstance(self.basis, Basis):
            raise ValueError("observation basis must be Basis")
        if not isinstance(self.reason, ObservationReason):
            raise ValueError("observation reason must be ObservationReason")
        if self.source is not None and not isinstance(self.source, SourceRef):
            raise ValueError("observation source must be SourceRef")

    def to_dict(self) -> dict[str, object]:
        return {
            "qubit_id": self.qubit_id,
            "basis": self.basis.to_dict(),
            "reason": self.reason.value,
            "source": self.source.to_dict() if self.source is not None else None,
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


def _validate_logical_qubit_ids(
    value: tuple[LogicalQubitId, ...],
    *,
    label: str,
    allow_empty: bool = False,
) -> None:
    if not isinstance(value, tuple) or (not value and not allow_empty):
        expected = "a tuple" if allow_empty else "a non-empty tuple"
        raise ValueError(f"{label} must be {expected}")
    for qubit_id in value:
        require_nonempty_identifier(qubit_id, label=label)
