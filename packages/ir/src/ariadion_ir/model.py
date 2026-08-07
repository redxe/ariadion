from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isclose, isfinite, pi, tau
from typing import Final

from ariadion_core import (
    ClassicalBitId,
    IrOperationId,
    LogicalOperationId,
    LogicalQubitId,
    ProgramId,
    SnapshotOperationId,
    SourceIdentity,
    SourceNodeId,
    SourceOperationId,
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
    RESET = "RESET"


_ROTATION_OPCODES = frozenset({OpCode.RX, OpCode.RY, OpCode.RZ})
_ANGLE_SOURCE_UNITS = frozenset({"degrees", "radians", "turns"})
_ANGLE_UNIT_TO_RADIANS = {
    "degrees": pi / 180,
    "radians": 1.0,
    "turns": tau,
}
_ANGLE_METADATA_RADIANS_ABS_TOLERANCE: Final = 1e-12
_ANGLE_METADATA_RADIANS_REL_TOLERANCE: Final = 1e-15


@dataclass(frozen=True, slots=True)
class CallFrameProvenance:
    """One semantic invocation frame retained beside an operation's definition source."""

    caller_program_id: ProgramId
    call_operation_id: LogicalOperationId
    callee_program_id: ProgramId
    call_source: SourceRef | None = None

    def __post_init__(self) -> None:
        require_nonempty_identifier(
            self.caller_program_id,
            label="call frame caller program ID",
        )
        require_nonempty_identifier(
            self.call_operation_id,
            label="call frame logical call operation ID",
        )
        require_nonempty_identifier(
            self.callee_program_id,
            label="call frame callee program ID",
        )
        if self.call_source is not None:
            if not isinstance(self.call_source, SourceRef):
                raise ValueError("call frame source must be SourceRef")
            if self.call_source.program_id != self.caller_program_id:
                raise ValueError("call frame source program ID must match its caller program ID")

    def to_dict(self) -> dict[str, object]:
        return {
            "caller_program_id": self.caller_program_id,
            "call_operation_id": self.call_operation_id,
            "callee_program_id": self.callee_program_id,
            "call_source": self.call_source.to_dict() if self.call_source is not None else None,
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class OperationProvenance:
    """Describes source operations and transformations behind generated IR."""

    parent_source_ids: tuple[SourceIdentity, ...] = ()
    transformation: str | None = None
    parent_logical_operation_ids: tuple[LogicalOperationId, ...] = ()
    call_stack: tuple[CallFrameProvenance, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.parent_source_ids, tuple):
            raise ValueError("provenance parent_source_ids must be a tuple")
        for source_id in self.parent_source_ids:
            require_nonempty_identifier(source_id, label="provenance parent source ID")
        if not isinstance(self.parent_logical_operation_ids, tuple):
            raise ValueError("provenance parent_logical_operation_ids must be a tuple")
        for logical_operation_id in self.parent_logical_operation_ids:
            require_nonempty_identifier(
                logical_operation_id,
                label="provenance parent logical operation ID",
            )
        if not isinstance(self.call_stack, tuple):
            raise ValueError("provenance call_stack must be a tuple")
        if not all(isinstance(frame, CallFrameProvenance) for frame in self.call_stack):
            raise ValueError("provenance call_stack must contain CallFrameProvenance values")

    def to_dict(self) -> dict[str, object]:
        return {
            "parent_source_ids": list(self.parent_source_ids),
            "transformation": self.transformation,
            "parent_logical_operation_ids": list(self.parent_logical_operation_ids),
            "call_stack": [frame.to_dict() for frame in self.call_stack],
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
class ObservationMetadata:
    """Resolved observation identity retained on a lowered measurement operation."""

    logical_qubit_id: LogicalQubitId
    result_id: ClassicalBitId
    basis_name: str
    reason: str

    def __post_init__(self) -> None:
        require_nonempty_identifier(
            self.logical_qubit_id,
            label="observation logical qubit ID",
        )
        require_nonempty_identifier(self.result_id, label="observation result ID")
        require_nonempty_identifier(self.basis_name, label="observation basis name")
        require_nonempty_identifier(self.reason, label="observation reason")

    def to_dict(self) -> dict[str, str]:
        return {
            "logical_qubit_id": self.logical_qubit_id,
            "result_id": self.result_id,
            "basis_name": self.basis_name,
            "reason": self.reason,
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
    observation: ObservationMetadata | None = None

    def __post_init__(self) -> None:
        require_nonempty_identifier(self.id, label="IR operation ID")
        if self.opcode is OpCode.RESET and (
            len(self.targets) != 1 or self.controls
        ):
            raise ValueError("RESET operations require exactly one uncontrolled target")
        if self.observation is not None:
            if not isinstance(self.observation, ObservationMetadata):
                raise ValueError("operation observation must be ObservationMetadata")
            if self.opcode is not OpCode.MEASURE:
                raise ValueError("only MEASURE operations can carry observation metadata")
            if self.key != str(self.observation.result_id):
                raise ValueError(
                    "observation measurement key must match the observation result ID"
                )
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
            if self.angle_metadata is not None:
                expected_angle_radians = (
                    self.angle_metadata.source_value
                    * _ANGLE_UNIT_TO_RADIANS[self.angle_metadata.source_unit]
                )
                if not isfinite(expected_angle_radians):
                    raise ValueError("rotation angle_metadata must produce finite radians")
                if not isclose(
                    angle_radians,
                    expected_angle_radians,
                    rel_tol=_ANGLE_METADATA_RADIANS_REL_TOLERANCE,
                    abs_tol=_ANGLE_METADATA_RADIANS_ABS_TOLERANCE,
                ):
                    raise ValueError(
                        "rotation angle_radians must match angle_metadata"
                    )
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
    def source_operation_id(self) -> SourceOperationId | None:
        return self.source.source_operation_id if self.source is not None else None

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
            "observation": (
                self.observation.to_dict() if self.observation is not None else None
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
