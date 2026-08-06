from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TypeAlias

from ariadion_core import (
    ClassicalBitId,
    LogicalOperationId,
    LogicalQubitId,
    ProgramId,
    SourceRef,
    canonical_json,
    require_nonempty_identifier,
)


SemanticSourceRef: TypeAlias = SourceRef


class FunctionEffect(str, Enum):
    """The reserved effect categories for future source-function analysis."""

    CLASSICAL = "classical"
    QUANTUM = "quantum"
    HYBRID = "hybrid"


class LogicalGateOpCode(str, Enum):
    """The currently modeled logical gate instruction forms."""

    X = "x"
    H = "h"
    Z = "z"
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
class BasisNamespace:
    """Public basis namespace kept distinct from gate-function names."""

    @property
    def x(self) -> Basis:
        return Basis("x")

    @property
    def y(self) -> Basis:
        return Basis("y")

    @property
    def z(self) -> Basis:
        return Basis("z")

    def named(self, name: str) -> Basis:
        return Basis(name)


basis = BasisNamespace()


@dataclass(frozen=True, slots=True)
class LogicalQubitValue:
    """A resolved logical quantum value before lifetime analysis or allocation."""

    id: LogicalQubitId
    display_name: str | None = None
    source: SemanticSourceRef | None = None

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
class ClassicalBitValue:
    """A declared classical result value before exact or sampled execution."""

    id: ClassicalBitId
    display_name: str | None = None
    source: SemanticSourceRef | None = None

    def __post_init__(self) -> None:
        require_nonempty_identifier(self.id, label="classical bit ID")
        if self.display_name is not None:
            require_nonempty_identifier(self.display_name, label="classical bit display name")
        if self.source is not None and not isinstance(self.source, SourceRef):
            raise ValueError("classical bit source must be SourceRef")

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "source": self.source.to_dict() if self.source is not None else None,
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class LogicalGateOperation:
    """One gate-shaped instruction over logical identities before allocation.

    This is intentionally one member of ``QuantumInstruction``, not the root of
    Ariadion's future physical language. Evolution, unitary, analog-interaction,
    and control-native instruction forms can join the union later.
    """

    id: LogicalOperationId
    opcode: LogicalGateOpCode
    targets: tuple[LogicalQubitId, ...]
    controls: tuple[LogicalQubitId, ...] = ()
    source: SemanticSourceRef | None = None

    def __post_init__(self) -> None:
        require_nonempty_identifier(self.id, label="logical operation ID")
        if not isinstance(self.opcode, LogicalGateOpCode):
            raise ValueError("logical gate operation opcode must be LogicalGateOpCode")
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
    """A semantic observation boundary with its own instruction identity."""

    id: LogicalOperationId
    qubit_id: LogicalQubitId
    result_id: ClassicalBitId
    basis: Basis
    reason: ObservationReason
    source: SemanticSourceRef | None = None

    def __post_init__(self) -> None:
        require_nonempty_identifier(self.id, label="observation logical operation ID")
        require_nonempty_identifier(self.qubit_id, label="observed logical qubit ID")
        require_nonempty_identifier(self.result_id, label="observation result ID")
        if not isinstance(self.basis, Basis):
            raise ValueError("observation basis must be Basis")
        if not isinstance(self.reason, ObservationReason):
            raise ValueError("observation reason must be ObservationReason")
        if self.source is not None and not isinstance(self.source, SourceRef):
            raise ValueError("observation source must be SourceRef")

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "qubit_id": self.qubit_id,
            "result_id": self.result_id,
            "basis": self.basis.to_dict(),
            "reason": self.reason.value,
            "source": self.source.to_dict() if self.source is not None else None,
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


QuantumInstruction: TypeAlias = LogicalGateOperation | Observation


@dataclass(frozen=True, slots=True)
class LogicalProgram:
    """An ordered pre-allocation quantum program over logical value identities."""

    id: ProgramId
    name: str
    qubits: tuple[LogicalQubitValue, ...]
    instructions: tuple[QuantumInstruction, ...]
    classical_bits: tuple[ClassicalBitValue, ...] = ()
    outputs: tuple[ClassicalBitId | LogicalQubitId, ...] = ()

    def __post_init__(self) -> None:
        require_nonempty_identifier(self.id, label="logical program ID")
        require_nonempty_identifier(self.name, label="logical program name")
        _require_tuple(self.qubits, label="logical program qubits")
        _require_tuple(self.instructions, label="logical program instructions")
        _require_tuple(self.classical_bits, label="logical program classical_bits")
        _require_tuple(self.outputs, label="logical program outputs")
        if not all(isinstance(qubit, LogicalQubitValue) for qubit in self.qubits):
            raise ValueError("logical program qubits must contain LogicalQubitValue values")
        if not all(isinstance(bit, ClassicalBitValue) for bit in self.classical_bits):
            raise ValueError(
                "logical program classical_bits must contain ClassicalBitValue values"
            )
        if not all(
            isinstance(instruction, (LogicalGateOperation, Observation))
            for instruction in self.instructions
        ):
            raise ValueError("logical program instructions must contain QuantumInstruction values")

        qubit_ids = tuple(qubit.id for qubit in self.qubits)
        _require_unique_identifiers(qubit_ids, label="logical program qubit IDs")
        known_qubit_ids = set(qubit_ids)
        for qubit in self.qubits:
            _validate_source_program(qubit.source, self.id, label="logical qubit")

        classical_bit_ids = tuple(bit.id for bit in self.classical_bits)
        _require_unique_identifiers(
            classical_bit_ids,
            label="logical program classical bit IDs",
        )
        known_classical_bit_ids = set(classical_bit_ids)
        if known_qubit_ids & known_classical_bit_ids:
            raise ValueError("logical qubit IDs and classical bit IDs must be distinct")
        for bit in self.classical_bits:
            _validate_source_program(bit.source, self.id, label="classical bit")

        instruction_ids = tuple(instruction.id for instruction in self.instructions)
        _require_unique_identifiers(
            instruction_ids,
            label="logical program instruction IDs",
        )
        observed_result_ids: list[ClassicalBitId] = []
        for instruction in self.instructions:
            _validate_source_program(
                instruction.source,
                self.id,
                label="logical instruction",
            )
            if isinstance(instruction, LogicalGateOperation):
                _validate_logical_gate_arity(instruction)
                referenced_qubits = instruction.controls + instruction.targets
            else:
                referenced_qubits = (instruction.qubit_id,)
                observed_result_ids.append(instruction.result_id)
                if instruction.result_id not in known_classical_bit_ids:
                    raise ValueError(
                        "logical observation references an undeclared classical bit: "
                        f"{instruction.result_id}"
                    )
            for qubit_id in referenced_qubits:
                if qubit_id not in known_qubit_ids:
                    raise ValueError(
                        "logical program instruction references an undeclared logical qubit: "
                        f"{qubit_id}"
                    )

        _require_unique_identifiers(
            tuple(observed_result_ids),
            label="logical program observation result IDs",
        )
        observed_result_id_set = set(observed_result_ids)
        unproduced_result_ids = known_classical_bit_ids - observed_result_id_set
        if unproduced_result_ids:
            missing_result_id = next(
                bit.id for bit in self.classical_bits if bit.id in unproduced_result_ids
            )
            raise ValueError(
                "logical program classical bit must have an observation producer: "
                f"{missing_result_id}"
            )
        for output in self.outputs:
            require_nonempty_identifier(output, label="logical program output ID")
            if output in known_classical_bit_ids:
                if output not in observed_result_id_set:
                    raise ValueError(
                        "logical program classical outputs must have an observation producer: "
                        f"{output}"
                    )
            elif output not in known_qubit_ids:
                raise ValueError(
                    "logical program output references an undeclared value: "
                    f"{output}"
                )

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
            "qubits": [qubit.to_dict() for qubit in self.qubits],
            "instructions": [instruction.to_dict() for instruction in self.instructions],
            "classical_bits": [bit.to_dict() for bit in self.classical_bits],
            "outputs": list(self.outputs),
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


def _require_tuple(value: object, *, label: str) -> None:
    if not isinstance(value, tuple):
        raise ValueError(f"{label} must be a tuple")


def _require_unique_identifiers(value: tuple[str, ...], *, label: str) -> None:
    if len(value) != len(set(value)):
        raise ValueError(f"{label} must be unique")


def _validate_source_program(
    source: SemanticSourceRef | None,
    program_id: ProgramId,
    *,
    label: str,
) -> None:
    if source is not None and source.program_id != program_id:
        raise ValueError(f"{label} source program ID must match logical program ID")


def _validate_logical_gate_arity(operation: LogicalGateOperation) -> None:
    if operation.opcode is LogicalGateOpCode.CX:
        if len(operation.controls) != 1 or len(operation.targets) != 1:
            raise ValueError("logical CX requires exactly one control and one target")
        if operation.controls[0] == operation.targets[0]:
            raise ValueError("logical CX requires distinct control and target qubits")
        return
    if len(operation.controls) != 0 or len(operation.targets) != 1:
        raise ValueError(
            f"logical {operation.opcode.value.upper()} requires exactly one target and no controls"
        )
