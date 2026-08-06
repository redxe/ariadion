from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite

from ariadion_core import (
    IrOperationId,
    ProgramId,
    SnapshotOperationId,
    SourceIdentity,
    SourceNodeId,
    SourceRange,
    SourceRef,
    canonical_json,
    require_nonempty_identifier,
)


class OpCode(str, Enum):
    X = "X"
    H = "H"
    Z = "Z"
    RX = "RX"
    RY = "RY"
    RZ = "RZ"
    CX = "CX"
    MEASURE = "MEASURE"


_ROTATION_OPCODES = frozenset({OpCode.RX, OpCode.RY, OpCode.RZ})
_ANGLE_SOURCE_UNITS = frozenset({"degrees", "radians", "turns"})


@dataclass(frozen=True, slots=True)
class OperationProvenance:
    """Describes source operations and transformations behind generated IR."""

    parent_source_ids: tuple[SourceIdentity, ...] = ()
    transformation: str | None = None

    def __post_init__(self) -> None:
        for source_id in self.parent_source_ids:
            require_nonempty_identifier(source_id, label="provenance parent source ID")

    def to_dict(self) -> dict[str, object]:
        return {
            "parent_source_ids": list(self.parent_source_ids),
            "transformation": self.transformation,
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class AngleMetadata:
    """Optional source-unit data retained alongside a canonical IR angle."""

    source_value: float
    source_unit: str

    def __post_init__(self) -> None:
        if isinstance(self.source_value, bool) or not isinstance(
            self.source_value,
            (int, float),
        ):
            raise ValueError("angle source_value must be numeric")
        source_value = float(self.source_value)
        if not isfinite(source_value):
            raise ValueError("angle source_value must be finite")
        if (
            not isinstance(self.source_unit, str)
            or self.source_unit not in _ANGLE_SOURCE_UNITS
        ):
            raise ValueError(
                "angle source_unit must be degrees, radians, or turns"
            )
        object.__setattr__(self, "source_value", source_value)

    def to_dict(self) -> dict[str, float | str]:
        return {
            "source_value": self.source_value,
            "source_unit": self.source_unit,
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class Operation:
    opcode: OpCode
    targets: tuple[int, ...]
    id: IrOperationId
    controls: tuple[int, ...] = ()
    key: str | None = None
    source: SourceRef | None = None
    provenance: OperationProvenance | None = None
    angle_radians: float | None = None
    angle_metadata: AngleMetadata | None = None

    def __post_init__(self) -> None:
        require_nonempty_identifier(self.id, label="IR operation ID")
        is_rotation = self.opcode in _ROTATION_OPCODES
        if is_rotation:
            if isinstance(self.angle_radians, bool) or not isinstance(
                self.angle_radians,
                (int, float),
            ):
                raise ValueError("rotation operations require a numeric angle_radians")
            angle_radians = float(self.angle_radians)
            if not isfinite(angle_radians):
                raise ValueError("rotation angle_radians must be finite")
            object.__setattr__(self, "angle_radians", angle_radians)
            if self.angle_metadata is not None and not isinstance(
                self.angle_metadata,
                AngleMetadata,
            ):
                raise ValueError("rotation angle_metadata must be AngleMetadata")
        elif self.angle_radians is not None or self.angle_metadata is not None:
            raise ValueError("only rotation operations can carry angle data")

    @property
    def source_id(self) -> SourceIdentity | None:
        return self.source.source_id if self.source is not None else None

    @property
    def program_id(self) -> ProgramId | None:
        return self.source.program_id if self.source is not None else None

    @property
    def snapshot_operation_id(self) -> SnapshotOperationId | None:
        return self.source.snapshot_operation_id if self.source is not None else None

    @property
    def source_node_id(self) -> SourceNodeId | None:
        return self.source.source_node_id if self.source is not None else None

    @property
    def source_range(self) -> SourceRange | None:
        return self.source.source_range if self.source is not None else None

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "opcode": self.opcode.value,
            "targets": list(self.targets),
            "controls": list(self.controls),
            "key": self.key,
            "angle_radians": self.angle_radians,
            "angle_metadata": (
                self.angle_metadata.to_dict() if self.angle_metadata is not None else None
            ),
            "source": self.source.to_dict() if self.source is not None else None,
            "provenance": (
                self.provenance.to_dict() if self.provenance is not None else None
            ),
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class CircuitIR:
    id: ProgramId
    name: str
    qubit_count: int
    operations: tuple[Operation, ...]

    def __post_init__(self) -> None:
        require_nonempty_identifier(self.id, label="program ID")

    def operation_count(self) -> int:
        return len(self.operations)

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
            "qubit_count": self.qubit_count,
            "operations": [operation.to_dict() for operation in self.operations],
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())
