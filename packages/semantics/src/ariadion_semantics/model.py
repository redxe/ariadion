from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isclose, isfinite, pi, tau
from typing import Final, TypeAlias

from ariadion_core import (
    ClassicalBitId,
    LogicalOperationId,
    LogicalQubitId,
    ProgramId,
    SourceRef,
    canonical_json,
    require_nonempty_identifier,
)
from ariadion_language import Angle, AngleUnit, Basis


SemanticSourceRef: TypeAlias = SourceRef
_SEMANTIC_ANGLE_RADIANS_ABS_TOLERANCE: Final = 1e-12
_SEMANTIC_ANGLE_RADIANS_REL_TOLERANCE: Final = 1e-15
_SEMANTIC_ANGLE_UNIT_TO_RADIANS = {
    "degrees": pi / 180,
    "radians": 1.0,
    "turns": tau,
}


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


class ReturnValueKind(str, Enum):
    """The explicit semantic kind of one scalar function-return value."""

    CLASSICAL_BIT = "classical_bit"
    QUANTUM_VALUE = "quantum_value"


class SemanticAngleUnit(str, Enum):
    """An explicit source unit preserved by a logical rotation instruction."""

    DEGREES = "degrees"
    RADIANS = "radians"
    TURNS = "turns"


class RotationAxis(str, Enum):
    """The axis of a typed logical rotation instruction."""

    X = "x"
    Y = "y"
    Z = "z"


@dataclass(frozen=True, slots=True)
class SemanticAngle:
    """A semantic source angle and its validated canonical-radians representation."""

    source_value: float
    source_unit: SemanticAngleUnit
    radians: float

    def __post_init__(self) -> None:
        if isinstance(self.source_value, bool) or not isinstance(
            self.source_value,
            (int, float),
        ):
            raise ValueError("semantic angle source_value must be numeric")
        source_value = float(self.source_value)
        if not isfinite(source_value):
            raise ValueError("semantic angle source_value must be finite")
        if not isinstance(self.source_unit, SemanticAngleUnit):
            raise ValueError("semantic angle source_unit must be a SemanticAngleUnit")
        if isinstance(self.radians, bool) or not isinstance(self.radians, (int, float)):
            raise ValueError("semantic angle radians must be numeric")
        radians = float(self.radians)
        if not isfinite(radians):
            raise ValueError("semantic angle radians must be finite")
        expected_radians = source_value * _SEMANTIC_ANGLE_UNIT_TO_RADIANS[
            self.source_unit.value
        ]
        if not isfinite(expected_radians):
            raise ValueError("semantic angle source value must produce finite radians")
        if not isclose(
            radians,
            expected_radians,
            rel_tol=_SEMANTIC_ANGLE_RADIANS_REL_TOLERANCE,
            abs_tol=_SEMANTIC_ANGLE_RADIANS_ABS_TOLERANCE,
        ):
            raise ValueError("semantic angle radians must match the source value and unit")
        object.__setattr__(self, "source_value", source_value)
        object.__setattr__(self, "radians", radians)

    @classmethod
    def from_angle(cls, angle: Angle) -> SemanticAngle:
        """Convert an explicit public ``Angle`` without accepting bare numerics."""

        if not isinstance(angle, Angle):
            raise ValueError("semantic angle conversion requires an Angle")
        source_unit = {
            AngleUnit.DEGREES: SemanticAngleUnit.DEGREES,
            AngleUnit.RADIANS: SemanticAngleUnit.RADIANS,
            AngleUnit.TURNS: SemanticAngleUnit.TURNS,
        }[angle.source_unit]
        return cls(angle.source_value, source_unit, angle.radians)

    def to_dict(self) -> dict[str, float | str]:
        return {
            "source_value": self.source_value,
            "source_unit": self.source_unit.value,
            "radians": self.radians,
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


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
class ObservationResultValue:
    """A declared classical value produced by one logical observation.

    This is intentionally narrower than Ariadion's eventual classical-value model.
    Future hybrid functions may also contain values from parameters, literals,
    computation, and backend metadata.
    """

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


ClassicalBitValue = ObservationResultValue


@dataclass(frozen=True, slots=True)
class ReturnValueRef:
    """A tagged scalar leaf in a semantic function-return structure."""

    kind: ReturnValueKind
    value_id: ClassicalBitId | LogicalQubitId

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ReturnValueKind):
            raise ValueError("return value kind must be a ReturnValueKind")
        require_nonempty_identifier(self.value_id, label="return value ID")

    def to_dict(self) -> dict[str, str]:
        return {"kind": self.kind.value, "value_id": self.value_id}

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class ScalarReturn:
    """A scalar return whose type is explicit in its value reference."""

    value: ReturnValueRef

    def __post_init__(self) -> None:
        if not isinstance(self.value, ReturnValueRef):
            raise ValueError("scalar return value must be a ReturnValueRef")

    def to_dict(self) -> dict[str, object]:
        return {"kind": "scalar", "value": self.value.to_dict()}

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class TupleReturn:
    """An ordered, recursively structured tuple return."""

    items: tuple[ReturnShape, ...]

    def __post_init__(self) -> None:
        _require_tuple(self.items, label="tuple return items")
        if not all(isinstance(item, (ScalarReturn, TupleReturn)) for item in self.items):
            raise ValueError("tuple return items must contain scalar or tuple return values")

    def to_dict(self) -> dict[str, object]:
        return {"kind": "tuple", "items": [item.to_dict() for item in self.items]}

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class NoneReturn:
    """The whole-function return contract for ``def function() -> None``.

    This is not ``typing.NoReturn`` and cannot appear inside a tuple return. A
    future scalar-``None`` value would require its own tagged return leaf.
    """

    def to_dict(self) -> dict[str, str]:
        return {"kind": "none"}

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


NoReturn = NoneReturn
"""Compatibility alias for :class:`NoneReturn`."""


ReturnShape: TypeAlias = ScalarReturn | TupleReturn | NoneReturn


def return_value_refs(return_shape: ReturnShape) -> tuple[ReturnValueRef, ...]:
    """Flatten tagged scalar leaves in deterministic left-to-right tree order."""

    if isinstance(return_shape, NoneReturn):
        return ()
    if isinstance(return_shape, ScalarReturn):
        return (return_shape.value,)
    if isinstance(return_shape, TupleReturn):
        return tuple(
            reference
            for item in return_shape.items
            for reference in return_value_refs(item)
        )
    raise ValueError("return shape must be a ReturnShape")


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
class LogicalRotationOperation:
    """One unit-bearing logical rotation before lowering to canonical IR radians."""

    id: LogicalOperationId
    axis: RotationAxis
    target: LogicalQubitId
    angle: SemanticAngle
    source: SemanticSourceRef | None = None

    def __post_init__(self) -> None:
        require_nonempty_identifier(self.id, label="logical rotation operation ID")
        if not isinstance(self.axis, RotationAxis):
            raise ValueError("logical rotation axis must be a RotationAxis")
        require_nonempty_identifier(self.target, label="logical rotation target")
        if not isinstance(self.angle, SemanticAngle):
            raise ValueError("logical rotation angle must be a SemanticAngle")
        if self.source is not None and not isinstance(self.source, SourceRef):
            raise ValueError("logical rotation source must be SourceRef")

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "axis": self.axis.value,
            "target": self.target,
            "angle": self.angle.to_dict(),
            "source": self.source.to_dict() if self.source is not None else None,
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class LogicalResetOperation:
    """Reset the state of one existing logical quantum value to ``|0>``."""

    id: LogicalOperationId
    qubit_id: LogicalQubitId
    source: SemanticSourceRef | None = None

    def __post_init__(self) -> None:
        require_nonempty_identifier(self.id, label="logical reset operation ID")
        require_nonempty_identifier(self.qubit_id, label="logical reset qubit ID")
        if self.source is not None and not isinstance(self.source, SourceRef):
            raise ValueError("logical reset source must be SourceRef")

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "qubit_id": self.qubit_id,
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


@dataclass(frozen=True, slots=True)
class QuantumArgumentBinding:
    """Bind one callee quantum parameter to a caller logical quantum value."""

    parameter_id: LogicalQubitId
    argument_id: LogicalQubitId

    def __post_init__(self) -> None:
        require_nonempty_identifier(
            self.parameter_id,
            label="quantum argument binding parameter ID",
        )
        require_nonempty_identifier(
            self.argument_id,
            label="quantum argument binding argument ID",
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "parameter_id": self.parameter_id,
            "argument_id": self.argument_id,
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class QuantumCallResult:
    """A caller-visible alias for one scalar quantum value returned by a call."""

    callee_value_id: LogicalQubitId
    caller_value_id: LogicalQubitId
    caller_binding_name: str | None = None
    source: SemanticSourceRef | None = None

    def __post_init__(self) -> None:
        require_nonempty_identifier(
            self.callee_value_id,
            label="quantum call result callee value ID",
        )
        require_nonempty_identifier(
            self.caller_value_id,
            label="quantum call result caller value ID",
        )
        if self.caller_binding_name is not None:
            require_nonempty_identifier(
                self.caller_binding_name,
                label="quantum call result caller binding name",
            )
        if self.source is not None and not isinstance(self.source, SourceRef):
            raise ValueError("quantum call result source must be SourceRef")

    def to_dict(self) -> dict[str, object]:
        return {
            "callee_value_id": self.callee_value_id,
            "caller_value_id": self.caller_value_id,
            "caller_binding_name": self.caller_binding_name,
            "source": self.source.to_dict() if self.source is not None else None,
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class LogicalCallOperation:
    """A semantic quantum-function invocation before its callee is lowered."""

    id: LogicalOperationId
    callee_program_id: ProgramId
    arguments: tuple[QuantumArgumentBinding, ...]
    source: SemanticSourceRef | None = None
    result: QuantumCallResult | None = None

    def __post_init__(self) -> None:
        require_nonempty_identifier(self.id, label="logical call operation ID")
        require_nonempty_identifier(
            self.callee_program_id,
            label="logical call callee program ID",
        )
        _require_tuple(self.arguments, label="logical call arguments")
        if not all(isinstance(argument, QuantumArgumentBinding) for argument in self.arguments):
            raise ValueError("logical call arguments must contain QuantumArgumentBinding values")
        parameter_ids = tuple(argument.parameter_id for argument in self.arguments)
        _require_unique_identifiers(
            parameter_ids,
            label="logical call bound parameter IDs",
        )
        if self.source is not None and not isinstance(self.source, SourceRef):
            raise ValueError("logical call source must be SourceRef")
        if self.result is not None and not isinstance(self.result, QuantumCallResult):
            raise ValueError("logical call result must be QuantumCallResult")

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "callee_program_id": self.callee_program_id,
            "arguments": [argument.to_dict() for argument in self.arguments],
            "source": self.source.to_dict() if self.source is not None else None,
            "result": self.result.to_dict() if self.result is not None else None,
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


QuantumInstruction: TypeAlias = (
    LogicalGateOperation
    | LogicalRotationOperation
    | LogicalResetOperation
    | Observation
    | LogicalCallOperation
)


@dataclass(frozen=True, slots=True)
class QuantumParameter:
    """One unbound source-level quantum input to a logical program."""

    name: str
    position: int
    logical_qubit_id: LogicalQubitId
    source: SemanticSourceRef | None = None

    def __post_init__(self) -> None:
        require_nonempty_identifier(self.name, label="quantum parameter name")
        if isinstance(self.position, bool) or not isinstance(self.position, int):
            raise ValueError("quantum parameter position must be an integer")
        if self.position < 0:
            raise ValueError("quantum parameter position must be non-negative")
        require_nonempty_identifier(
            self.logical_qubit_id,
            label="quantum parameter logical qubit ID",
        )
        if self.source is not None and not isinstance(self.source, SourceRef):
            raise ValueError("quantum parameter source must be SourceRef")

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "position": self.position,
            "logical_qubit_id": self.logical_qubit_id,
            "source": self.source.to_dict() if self.source is not None else None,
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


class UnboundQuantumParameterError(ValueError):
    """Raised when standalone execution would initialize an unresolved quantum input."""

    code = "P113"

    def __init__(self, parameters: tuple[QuantumParameter, ...]) -> None:
        self.parameters = parameters
        self.program_id = (
            parameters[0].source.program_id
            if parameters and parameters[0].source is not None
            else None
        )
        self.source_range = (
            parameters[0].source.source_range
            if parameters and parameters[0].source is not None
            else None
        )
        names = ", ".join(parameter.name for parameter in parameters)
        super().__init__(
            f"{self.code} unbound quantum parameter(s): {names}. "
            "Quantum functions with parameters cannot run independently."
        )


@dataclass(frozen=True, slots=True)
class LogicalProgram:
    """An ordered pre-allocation quantum program over logical value identities."""

    id: ProgramId
    name: str
    qubits: tuple[LogicalQubitValue, ...]
    instructions: tuple[QuantumInstruction, ...]
    classical_bits: tuple[ObservationResultValue, ...] = ()
    return_shape: ReturnShape = NoneReturn()
    parameters: tuple[QuantumParameter, ...] = ()

    def __post_init__(self) -> None:
        require_nonempty_identifier(self.id, label="logical program ID")
        require_nonempty_identifier(self.name, label="logical program name")
        _require_tuple(self.qubits, label="logical program qubits")
        _require_tuple(self.instructions, label="logical program instructions")
        _require_tuple(self.classical_bits, label="logical program classical_bits")
        _require_tuple(self.parameters, label="logical program parameters")
        if not isinstance(self.return_shape, (ScalarReturn, TupleReturn, NoneReturn)):
            raise ValueError("logical program return_shape must be a ReturnShape")
        if not all(isinstance(qubit, LogicalQubitValue) for qubit in self.qubits):
            raise ValueError("logical program qubits must contain LogicalQubitValue values")
        if not all(isinstance(bit, ObservationResultValue) for bit in self.classical_bits):
            raise ValueError(
                "logical program classical_bits must contain ObservationResultValue values"
            )
        if not all(isinstance(parameter, QuantumParameter) for parameter in self.parameters):
            raise ValueError("logical program parameters must contain QuantumParameter values")
        if not all(
            isinstance(
                instruction,
                (
                    LogicalGateOperation,
                    LogicalRotationOperation,
                    LogicalResetOperation,
                    Observation,
                    LogicalCallOperation,
                ),
            )
            for instruction in self.instructions
        ):
            raise ValueError("logical program instructions must contain QuantumInstruction values")

        qubit_ids = tuple(qubit.id for qubit in self.qubits)
        _require_unique_identifiers(qubit_ids, label="logical program qubit IDs")
        known_qubit_ids = set(qubit_ids)
        for qubit in self.qubits:
            _validate_source_program(qubit.source, self.id, label="logical qubit")

        parameter_names = tuple(parameter.name for parameter in self.parameters)
        _require_unique_identifiers(parameter_names, label="logical program parameter names")
        parameter_ids = tuple(parameter.logical_qubit_id for parameter in self.parameters)
        _require_unique_identifiers(
            parameter_ids,
            label="logical program parameter logical qubit IDs",
        )
        if tuple(parameter.position for parameter in self.parameters) != tuple(
            range(len(self.parameters))
        ):
            raise ValueError("logical program parameter positions must be contiguous from zero")
        for parameter in self.parameters:
            _validate_source_program(parameter.source, self.id, label="quantum parameter")
            if parameter.logical_qubit_id not in known_qubit_ids:
                raise ValueError(
                    "quantum parameter must reference a declared logical qubit: "
                    f"{parameter.logical_qubit_id}"
                )

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
        observed_qubit_ids: set[LogicalQubitId] = set()
        known_quantum_value_ids = set(known_qubit_ids)
        for instruction in self.instructions:
            _validate_source_program(
                instruction.source,
                self.id,
                label="logical instruction",
            )
            if isinstance(instruction, LogicalGateOperation):
                _validate_logical_gate_arity(instruction)
                referenced_qubits = instruction.controls + instruction.targets
            elif isinstance(instruction, LogicalRotationOperation):
                referenced_qubits = (instruction.target,)
            elif isinstance(instruction, LogicalResetOperation):
                referenced_qubits = (instruction.qubit_id,)
            elif isinstance(instruction, LogicalCallOperation):
                for binding in instruction.arguments:
                    if binding.argument_id not in known_quantum_value_ids:
                        raise ValueError(
                            "logical call argument references an undeclared logical quantum "
                            f"value: {binding.argument_id}"
                        )
                if instruction.result is not None:
                    _validate_source_program(
                        instruction.result.source,
                        self.id,
                        label="logical call result",
                    )
                    if instruction.result.caller_value_id in known_quantum_value_ids:
                        raise ValueError(
                            "logical call result caller value ID must be new within its "
                            f"program: {instruction.result.caller_value_id}"
                        )
                    known_quantum_value_ids.add(instruction.result.caller_value_id)
                continue
            else:
                referenced_qubits = (instruction.qubit_id,)
                observed_qubit_ids.add(instruction.qubit_id)
                observed_result_ids.append(instruction.result_id)
                if instruction.result_id not in known_classical_bit_ids:
                    raise ValueError(
                        "logical observation references an undeclared classical bit: "
                        f"{instruction.result_id}"
                    )
            for qubit_id in referenced_qubits:
                if qubit_id not in known_quantum_value_ids:
                    raise ValueError(
                        "logical program instruction references an undeclared logical qubit "
                        "or quantum value: "
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
        for reference in return_value_refs(self.return_shape):
            if reference.kind is ReturnValueKind.CLASSICAL_BIT:
                if reference.value_id in known_classical_bit_ids:
                    if reference.value_id not in observed_result_id_set:
                        raise ValueError(
                            "classical return must have an observation producer: "
                            f"{reference.value_id}"
                        )
                elif reference.value_id in known_quantum_value_ids:
                    raise ValueError(
                        "classical return kind cannot reference a logical qubit ID: "
                        f"{reference.value_id}"
                    )
                else:
                    raise ValueError(
                        "classical return references an undeclared observation result: "
                        f"{reference.value_id}"
                    )
            elif reference.kind is ReturnValueKind.QUANTUM_VALUE:
                if reference.value_id in known_quantum_value_ids:
                    if reference.value_id in observed_qubit_ids:
                        raise ValueError(
                            "quantum return cannot reference an observed logical qubit: "
                            f"{reference.value_id}"
                        )
                elif reference.value_id in known_classical_bit_ids:
                    raise ValueError(
                        "quantum return kind cannot reference a classical observation result: "
                        f"{reference.value_id}"
                    )
                else:
                    raise ValueError(
                        "quantum return references an undeclared logical qubit: "
                        f"{reference.value_id}"
                    )
            else:  # pragma: no cover - protects future enum expansion
                raise ValueError(f"unsupported return value kind: {reference.kind}")

    @property
    def outputs(self) -> tuple[ClassicalBitId | LogicalQubitId, ...]:
        """Compatibility view that flattens return leaves without driving lowering."""

        return tuple(reference.value_id for reference in return_value_refs(self.return_shape))

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
            "qubits": [qubit.to_dict() for qubit in self.qubits],
            "instructions": [instruction.to_dict() for instruction in self.instructions],
            "classical_bits": [bit.to_dict() for bit in self.classical_bits],
            "return_shape": self.return_shape.to_dict(),
            "parameters": [parameter.to_dict() for parameter in self.parameters],
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class LogicalModule:
    """A resolved, acyclic aggregate of logical quantum programs and calls."""

    entry_program_id: ProgramId
    programs: tuple[LogicalProgram, ...]

    def __post_init__(self) -> None:
        require_nonempty_identifier(self.entry_program_id, label="logical module entry program ID")
        _require_tuple(self.programs, label="logical module programs")
        if not all(isinstance(program, LogicalProgram) for program in self.programs):
            raise ValueError("logical module programs must contain LogicalProgram values")

        program_ids = tuple(program.id for program in self.programs)
        _require_unique_identifiers(program_ids, label="logical module program IDs")
        programs_by_id = {program.id: program for program in self.programs}
        if self.entry_program_id not in programs_by_id:
            raise ValueError("logical module entry program must be declared in programs")

        call_edges: dict[ProgramId, tuple[ProgramId, ...]] = {}
        for caller in self.programs:
            caller_value_ids = {qubit.id for qubit in caller.qubits}
            callees: list[ProgramId] = []
            for instruction in caller.instructions:
                if not isinstance(instruction, LogicalCallOperation):
                    continue
                callee = programs_by_id.get(instruction.callee_program_id)
                if callee is None:
                    raise ValueError(
                        "logical call references a program outside its logical module: "
                        f"{instruction.callee_program_id}"
                    )
                callees.append(callee.id)
                expected_parameter_ids = tuple(
                    parameter.logical_qubit_id for parameter in callee.parameters
                )
                bindings = instruction.arguments
                if len(bindings) != len(expected_parameter_ids):
                    raise ValueError(
                        "logical call arity must match the callee quantum parameter count"
                    )
                bound_parameter_ids = tuple(
                    binding.parameter_id for binding in bindings
                )
                if bound_parameter_ids != expected_parameter_ids:
                    raise ValueError(
                        "logical call bindings must bind each callee parameter exactly once "
                        "in declared position order"
                    )
                for binding in bindings:
                    if binding.argument_id not in caller_value_ids:
                        raise ValueError(
                            "logical call argument must reference a logical value declared "
                            f"by its caller: {binding.argument_id}"
                        )
                if instruction.result is None:
                    if not isinstance(callee.return_shape, NoneReturn):
                        raise ValueError(
                            "logical calls without a result binding require a None-returning "
                            "callee"
                        )
                    continue
                if (
                    not isinstance(callee.return_shape, ScalarReturn)
                    or callee.return_shape.value.kind is not ReturnValueKind.QUANTUM_VALUE
                ):
                    raise ValueError(
                        "logical call result bindings require a scalar quantum-returning callee"
                    )
                if (
                    callee.return_shape.value.value_id
                    != instruction.result.callee_value_id
                ):
                    raise ValueError(
                        "logical call result must reference the callee scalar quantum return"
                    )
                if instruction.result.caller_value_id in caller_value_ids:
                    raise ValueError(
                        "logical call result caller value ID must be new within its caller"
                    )
                caller_value_ids.add(instruction.result.caller_value_id)
            call_edges[caller.id] = tuple(callees)

        visited: set[ProgramId] = set()
        visiting: set[ProgramId] = set()

        def visit(program_id: ProgramId) -> None:
            if program_id in visiting:
                raise ValueError("logical module quantum call graph must be acyclic")
            if program_id in visited:
                return
            visiting.add(program_id)
            for callee_program_id in call_edges[program_id]:
                visit(callee_program_id)
            visiting.remove(program_id)
            visited.add(program_id)

        for program_id in program_ids:
            visit(program_id)

    @property
    def entry_program(self) -> LogicalProgram:
        """Return the validated entry program without coupling it to a frontend."""

        return next(program for program in self.programs if program.id == self.entry_program_id)

    def to_dict(self) -> dict[str, object]:
        return {
            "entry_program_id": self.entry_program_id,
            "programs": [
                program.to_dict()
                for program in sorted(self.programs, key=lambda program: str(program.id))
            ],
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
