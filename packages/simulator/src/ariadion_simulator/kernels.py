"""Inspectable operator-structure metadata for simulation kernels.

The metadata describes how an operation can be applied; it does not alter IR
semantics or force any backend framework. A numerical backend may use it to
select an indexed permutation, a diagonal multiply, or a local tensor kernel.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ariadion_core import IrOperationId, canonical_json, require_nonempty_identifier
from ariadion_ir import OpCode, Operation


class OperatorStructure(str, Enum):
    """Mathematical structure relevant to a local simulation kernel."""

    PERMUTATION = "permutation"
    DIAGONAL = "diagonal"
    LOCAL_DENSE = "local_dense"
    CONTROLLED_PERMUTATION = "controlled_permutation"
    KRAUS_CHANNEL = "kraus_channel"


@dataclass(frozen=True, slots=True)
class KernelMetadata:
    """One inspectable implementation category for an allocated operation."""

    operation_id: IrOperationId
    structure: OperatorStructure
    detail: str

    def __post_init__(self) -> None:
        require_nonempty_identifier(
            self.operation_id,
            label="kernel metadata operation ID",
        )
        if not isinstance(self.structure, OperatorStructure):
            raise ValueError("kernel metadata structure must be OperatorStructure")
        if not isinstance(self.detail, str) or not self.detail:
            raise ValueError("kernel metadata detail must be a non-empty string")

    def to_dict(self) -> dict[str, str]:
        return {
            "operation_id": self.operation_id,
            "structure": self.structure.value,
            "detail": self.detail,
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


def kernel_metadata_for_operation(
    operation: Operation,
    *,
    has_quantum_channel: bool = False,
) -> tuple[KernelMetadata, ...]:
    """Return ordered ideal and optional post-gate channel kernel evidence.

    ``MEASURE`` is a semantic observation rather than an evolution kernel and
    therefore yields no metadata. ``RESET`` is explicitly a trace-and-reprepare
    CPTP channel. When ``has_quantum_channel`` is true, the returned channel
    entry is applied after the ideal one-qubit gate.
    """

    if not isinstance(operation, Operation):
        raise ValueError("kernel metadata operation must be Operation")
    structure, detail = _ideal_structure(operation.opcode)
    if structure is None:
        return ()
    metadata = [KernelMetadata(operation.id, structure, detail)]
    if has_quantum_channel:
        if operation.opcode not in {
            OpCode.X,
            OpCode.H,
            OpCode.Z,
            OpCode.RX,
            OpCode.RY,
            OpCode.RZ,
        }:
            raise ValueError("only ideal one-qubit gates can have a post-gate Kraus channel")
        metadata.append(
            KernelMetadata(
                operation.id,
                OperatorStructure.KRAUS_CHANNEL,
                "typed one-qubit Kraus channel applied after the ideal gate",
            )
        )
    return tuple(metadata)


def _ideal_structure(opcode: OpCode) -> tuple[OperatorStructure | None, str]:
    if opcode is OpCode.X:
        return OperatorStructure.PERMUTATION, "one-qubit computational-basis swap"
    if opcode in {OpCode.Z, OpCode.RZ}:
        return OperatorStructure.DIAGONAL, "one-qubit computational-basis phase"
    if opcode in {OpCode.H, OpCode.RX, OpCode.RY}:
        return OperatorStructure.LOCAL_DENSE, "one-qubit dense 2x2 transform"
    if opcode is OpCode.CX:
        return OperatorStructure.CONTROLLED_PERMUTATION, "controlled basis-index swap"
    if opcode is OpCode.RESET:
        return OperatorStructure.KRAUS_CHANNEL, "trace-and-reprepare reset channel"
    if opcode is OpCode.MEASURE:
        return None, "terminal analytical observation"
    raise ValueError(f"unsupported operation opcode for kernel metadata: {opcode}")


__all__ = [
    "KernelMetadata",
    "OperatorStructure",
    "kernel_metadata_for_operation",
]
