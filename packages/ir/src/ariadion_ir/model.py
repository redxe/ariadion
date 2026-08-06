from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

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
    CX = "CX"
    MEASURE = "MEASURE"


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
class Operation:
    opcode: OpCode
    targets: tuple[int, ...]
    id: IrOperationId
    controls: tuple[int, ...] = ()
    key: str | None = None
    source: SourceRef | None = None
    provenance: OperationProvenance | None = None

    def __post_init__(self) -> None:
        require_nonempty_identifier(self.id, label="IR operation ID")

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
