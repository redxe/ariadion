from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
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
from ariadion_ir import (
    AngleMetadata,
    CallFrameProvenance,
    CircuitIR,
    ObservationMetadata,
    OpCode,
    Operation,
    OperationProvenance,
)
from ariadion_language import Angle, Basis, Program, SourceOperation
from ariadion_semantics import (
    LogicalCallOperation,
    LogicalGateOpCode,
    LogicalGateOperation,
    LogicalModule,
    LogicalProgram,
    LogicalRotationOperation,
    NoneReturn,
    Observation,
    ObservationReason,
    ReturnShape,
    ReturnValueKind,
    RotationAxis,
    ScalarReturn,
    TupleReturn,
    return_value_refs,
)

from .expansion import (
    CallExpansionPlan,
    ExpandedLogicalInstruction,
    ExpandedLogicalProgram,
    LogicalLifetimeAnalysis,
    LogicalQubitOrigin,
    analyze_logical_lifetimes,
    expand_logical_module,
)


class DiagnosticSeverity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True, slots=True)
class Diagnostic:
    code: str
    message: str
    operation_index: int | None = None
    source: SourceRef | None = None
    severity: DiagnosticSeverity = DiagnosticSeverity.ERROR
    logical_operation_id: LogicalOperationId | None = None

    @property
    def source_id(self) -> SourceIdentity | None:
        return self.source.source_id if self.source is not None else None

    @property
    def source_range(self) -> SourceRange | None:
        return self.source.source_range if self.source is not None else None

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

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": self.message,
            "operation_index": self.operation_index,
            "severity": self.severity.value,
            "logical_operation_id": self.logical_operation_id,
            "source": self.source.to_dict() if self.source is not None else None,
        }


class CompileError(ValueError):
    def __init__(self, diagnostics: tuple[Diagnostic, ...]) -> None:
        self.diagnostics = diagnostics
        super().__init__("; ".join(item.message for item in diagnostics))


LOGICAL_ALLOCATION_POLICY_NAME: Final = "dense-no-reuse-v1"
EXPANDED_LOGICAL_ALLOCATION_POLICY_NAME: Final = "expanded-dense-no-reuse-v1"
_LOGICAL_LOWERING_TRANSFORMATION: Final = "logical-allocation-lowering"
_Z_BASIS_NAME: Final = "z"


@dataclass(frozen=True, slots=True)
class LogicalSlotAllocationEntry:
    """The execution slot selected for one logical value before hardware mapping."""

    logical_qubit_id: LogicalQubitId
    display_name: str | None
    slot: int
    origin: LogicalQubitOrigin | None = None

    def __post_init__(self) -> None:
        require_nonempty_identifier(
            self.logical_qubit_id,
            label="logical slot allocation qubit ID",
        )
        if self.display_name is not None:
            require_nonempty_identifier(
                self.display_name,
                label="logical slot allocation display name",
            )
        _require_nonnegative_int(self.slot, label="logical slot allocation slot")
        if self.origin is not None and not isinstance(self.origin, LogicalQubitOrigin):
            raise ValueError("logical slot allocation origin must be LogicalQubitOrigin")

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "logical_qubit_id": self.logical_qubit_id,
            "display_name": self.display_name,
            "slot": self.slot,
        }
        if self.origin is not None:
            result["origin"] = self.origin.to_dict()
        return result

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class LogicalSlotAllocationPlan:
    """Managed logical values mapped to dense execution slots, not hardware qubits."""

    policy_name: str
    entries: tuple[LogicalSlotAllocationEntry, ...]
    peak_live_qubits: int
    allocated_qubit_count: int

    def __post_init__(self) -> None:
        require_nonempty_identifier(self.policy_name, label="allocation policy name")
        if not isinstance(self.entries, tuple):
            raise ValueError("logical slot allocation entries must be a tuple")
        if not all(isinstance(entry, LogicalSlotAllocationEntry) for entry in self.entries):
            raise ValueError(
                "logical slot allocation entries must contain LogicalSlotAllocationEntry values"
            )
        logical_ids = tuple(entry.logical_qubit_id for entry in self.entries)
        if len(logical_ids) != len(set(logical_ids)):
            raise ValueError("logical slot allocation qubit IDs must be unique")
        _require_nonnegative_int(
            self.peak_live_qubits,
            label="logical slot allocation peak_live_qubits",
        )
        _require_nonnegative_int(
            self.allocated_qubit_count,
            label="logical slot allocation allocated_qubit_count",
        )
        if self.peak_live_qubits > self.allocated_qubit_count:
            raise ValueError(
                "logical slot allocation peak_live_qubits cannot exceed allocated_qubit_count"
            )
        if any(entry.slot >= self.allocated_qubit_count for entry in self.entries):
            raise ValueError(
                "logical slot allocation entry slot must fit allocated_qubit_count"
            )
        if self.policy_name in {
            LOGICAL_ALLOCATION_POLICY_NAME,
            EXPANDED_LOGICAL_ALLOCATION_POLICY_NAME,
        }:
            expected_slots = tuple(range(len(self.entries)))
            if tuple(entry.slot for entry in self.entries) != expected_slots:
                raise ValueError(
                    "dense-no-reuse logical slot allocation entries must use declaration-order "
                    "dense slots"
                )
            if (
                self.policy_name == LOGICAL_ALLOCATION_POLICY_NAME
                and self.peak_live_qubits != len(self.entries)
            ):
                raise ValueError(
                    "dense-no-reuse logical slot allocation peak_live_qubits must equal entry "
                    "count"
                )
            if self.allocated_qubit_count != len(self.entries):
                raise ValueError(
                    "dense-no-reuse logical slot allocation allocated_qubit_count must equal "
                    "entry count"
                )
        if (
            self.policy_name == EXPANDED_LOGICAL_ALLOCATION_POLICY_NAME
            and any(entry.origin is None for entry in self.entries)
        ):
            raise ValueError(
                "expanded logical slot allocation entries must preserve logical qubit origins"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "policy_name": self.policy_name,
            "entries": [entry.to_dict() for entry in self.entries],
            "peak_live_qubits": self.peak_live_qubits,
            "allocated_qubit_count": self.allocated_qubit_count,
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


AllocationEntry = LogicalSlotAllocationEntry
AllocationPlan = LogicalSlotAllocationPlan


@dataclass(frozen=True, slots=True)
class AllocatedObservation:
    """One logical observation bound to its result and allocated execution slot."""

    result_id: ClassicalBitId
    result_display_name: str | None
    logical_qubit_id: LogicalQubitId
    allocated_slot: int
    basis: Basis
    reason: ObservationReason
    logical_operation_id: LogicalOperationId

    def __post_init__(self) -> None:
        require_nonempty_identifier(self.result_id, label="allocated observation result ID")
        if self.result_display_name is not None:
            require_nonempty_identifier(
                self.result_display_name,
                label="allocated observation result display name",
            )
        require_nonempty_identifier(
            self.logical_qubit_id,
            label="allocated observation logical qubit ID",
        )
        _require_nonnegative_int(
            self.allocated_slot,
            label="allocated observation slot",
        )
        if not isinstance(self.basis, Basis):
            raise ValueError("allocated observation basis must be Basis")
        if not isinstance(self.reason, ObservationReason):
            raise ValueError("allocated observation reason must be ObservationReason")
        require_nonempty_identifier(
            self.logical_operation_id,
            label="allocated observation logical operation ID",
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "result_id": self.result_id,
            "result_display_name": self.result_display_name,
            "logical_qubit_id": self.logical_qubit_id,
            "allocated_slot": self.allocated_slot,
            "basis": self.basis.to_dict(),
            "reason": self.reason.value,
            "logical_operation_id": self.logical_operation_id,
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class ReadoutPlan:
    """Lowered observations plus the source-preserved structured function return."""

    observations: tuple[AllocatedObservation, ...]
    return_shape: ReturnShape

    def __post_init__(self) -> None:
        if not isinstance(self.observations, tuple):
            raise ValueError("readout plan observations must be a tuple")
        if not all(isinstance(item, AllocatedObservation) for item in self.observations):
            raise ValueError("readout plan observations must contain AllocatedObservation values")
        result_ids = tuple(item.result_id for item in self.observations)
        if len(result_ids) != len(set(result_ids)):
            raise ValueError("readout plan observation result IDs must be unique")
        operation_ids = tuple(item.logical_operation_id for item in self.observations)
        if len(operation_ids) != len(set(operation_ids)):
            raise ValueError("readout plan logical operation IDs must be unique")
        if not isinstance(self.return_shape, (ScalarReturn, TupleReturn, NoneReturn)):
            raise ValueError("readout plan return_shape must be a ReturnShape")
        known_result_ids = set(result_ids)
        for result_id in self.classical_return_ids():
            if result_id not in known_result_ids:
                raise ValueError(
                    "readout plan classical return must reference a lowered observation: "
                    f"{result_id}"
                )

    def classical_return_ids(self) -> tuple[ClassicalBitId, ...]:
        """Flatten only classical leaves in deterministic left-to-right order."""

        return tuple(
            ClassicalBitId(reference.value_id)
            for reference in return_value_refs(self.return_shape)
            if reference.kind is ReturnValueKind.CLASSICAL_BIT
        )

    def quantum_return_ids(self) -> tuple[LogicalQubitId, ...]:
        """Flatten only quantum leaves in deterministic left-to-right order."""

        return tuple(
            LogicalQubitId(reference.value_id)
            for reference in return_value_refs(self.return_shape)
            if reference.kind is ReturnValueKind.QUANTUM_VALUE
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "observations": [item.to_dict() for item in self.observations],
            "return_shape": self.return_shape.to_dict(),
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class LogicalCompilationResult:
    """Allocated IR, logical slots, and ordered readout for one logical program."""

    ir: CircuitIR
    logical_allocation: LogicalSlotAllocationPlan
    readout: ReadoutPlan
    expanded_program: ExpandedLogicalProgram | None = None
    call_expansion: CallExpansionPlan | None = None
    lifetime_analysis: LogicalLifetimeAnalysis | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.ir, CircuitIR):
            raise ValueError("logical compilation result ir must be CircuitIR")
        if not isinstance(self.logical_allocation, LogicalSlotAllocationPlan):
            raise ValueError(
                "logical compilation result logical_allocation must be "
                "LogicalSlotAllocationPlan"
            )
        if not isinstance(self.readout, ReadoutPlan):
            raise ValueError("logical compilation result readout must be ReadoutPlan")
        module_evidence = (
            self.expanded_program,
            self.call_expansion,
            self.lifetime_analysis,
        )
        if any(item is None for item in module_evidence) and not all(
            item is None for item in module_evidence
        ):
            raise ValueError(
                "logical compilation result module evidence must be supplied together"
            )
        if self.expanded_program is not None:
            if not isinstance(self.call_expansion, CallExpansionPlan):
                raise ValueError(
                    "logical compilation result call_expansion must be CallExpansionPlan"
                )
            if not isinstance(self.lifetime_analysis, LogicalLifetimeAnalysis):
                raise ValueError(
                    "logical compilation result lifetime_analysis must be LogicalLifetimeAnalysis"
                )
            expanded_qubit_ids = tuple(qubit.id for qubit in self.expanded_program.qubits)
            allocation_qubit_ids = tuple(
                entry.logical_qubit_id for entry in self.logical_allocation.entries
            )
            if allocation_qubit_ids != expanded_qubit_ids:
                raise ValueError(
                    "module logical allocation entries must match expanded logical qubits"
                )
            if tuple(entry.origin for entry in self.logical_allocation.entries) != tuple(
                qubit.origin for qubit in self.expanded_program.qubits
            ):
                raise ValueError(
                    "module logical allocation origins must match expanded logical qubits"
                )
            if self.ir.id != self.expanded_program.id:
                raise ValueError(
                    "module compilation IR ID must match the expanded logical program"
                )
            if self.call_expansion != self.expanded_program.call_expansion:
                raise ValueError(
                    "module call expansion evidence must match the expanded logical program"
                )
            lifetime_ids = tuple(
                lifetime.logical_qubit_id for lifetime in self.lifetime_analysis.lifetimes
            )
            if lifetime_ids != expanded_qubit_ids:
                raise ValueError(
                    "module lifetime evidence must match expanded logical qubits"
                )
            if self.readout.return_shape != self.expanded_program.return_shape:
                raise ValueError(
                    "module readout return shape must match expanded logical program"
                )
        if self.ir.qubit_count != self.logical_allocation.allocated_qubit_count:
            raise ValueError(
                "logical compilation result IR qubit_count must match allocated_qubit_count"
            )
        slots = {
            entry.logical_qubit_id: entry.slot
            for entry in self.logical_allocation.entries
        }
        for observation in self.readout.observations:
            if slots.get(observation.logical_qubit_id) != observation.allocated_slot:
                raise ValueError(
                    "readout observation slot must match the logical slot allocation"
                )
            matching_operations = tuple(
                operation
                for operation in self.ir.operations
                if operation.observation is not None
                and operation.observation.result_id == observation.result_id
            )
            if len(matching_operations) != 1:
                raise ValueError(
                    "readout observation must match exactly one IR observation measurement"
                )
            operation = matching_operations[0]
            metadata = operation.observation
            assert metadata is not None
            if (
                operation.opcode is not OpCode.MEASURE
                or operation.targets != (observation.allocated_slot,)
                or operation.key != str(observation.result_id)
                or metadata.logical_qubit_id != observation.logical_qubit_id
                or metadata.basis_name != observation.basis.name
                or metadata.reason != observation.reason.value
                or operation.provenance is None
                or (
                    operation.provenance.parent_logical_operation_ids
                    != (observation.logical_operation_id,)
                )
            ):
                raise ValueError("readout observation must match its IR measurement metadata")
        known_result_ids = {observation.result_id for observation in self.readout.observations}
        if any(
            result_id not in known_result_ids
            for result_id in self.readout.classical_return_ids()
        ):
            raise ValueError("readout classical returns must reference lowered observations")
        if any(
            qubit_id not in slots
            for qubit_id in self.readout.quantum_return_ids()
        ):
            raise ValueError("readout quantum returns must reference allocated logical qubits")

    @property
    def allocation(self) -> LogicalSlotAllocationPlan:
        """Compatibility alias for the pre-readout logical slot allocation field."""

        return self.logical_allocation

    def to_dict(self) -> dict[str, object]:
        return {
            "ir": self.ir.to_dict(),
            "logical_allocation": self.logical_allocation.to_dict(),
            "readout": self.readout.to_dict(),
            "expanded_program": (
                self.expanded_program.to_dict()
                if self.expanded_program is not None
                else None
            ),
            "call_expansion": (
                self.call_expansion.to_dict() if self.call_expansion is not None else None
            ),
            "lifetime_analysis": (
                self.lifetime_analysis.to_dict()
                if self.lifetime_analysis is not None
                else None
            ),
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


_OPCODE_MAP = {
    "x": OpCode.X,
    "h": OpCode.H,
    "z": OpCode.Z,
    "rx": OpCode.RX,
    "ry": OpCode.RY,
    "rz": OpCode.RZ,
    "cx": OpCode.CX,
    "measure": OpCode.MEASURE,
}

_ROTATION_NAMES = frozenset({"rx", "ry", "rz"})
_LOGICAL_GATE_OPCODE_MAP = {
    LogicalGateOpCode.X: OpCode.X,
    LogicalGateOpCode.H: OpCode.H,
    LogicalGateOpCode.Z: OpCode.Z,
    LogicalGateOpCode.CX: OpCode.CX,
}
_LOGICAL_ROTATION_OPCODE_MAP = {
    RotationAxis.X: OpCode.RX,
    RotationAxis.Y: OpCode.RY,
    RotationAxis.Z: OpCode.RZ,
}


def compile_program(program: Program) -> CircuitIR:
    diagnostics = _validate(program)
    if diagnostics:
        raise CompileError(tuple(diagnostics))

    operations = tuple(_lower(program, operation) for operation in program.operations)
    return CircuitIR(program.id, program.name, program.qubit_count, operations)


def compile_logical_program(program: LogicalProgram) -> LogicalCompilationResult:
    """Allocate and lower a hand-built logical program without reusing slots."""

    if not isinstance(program, LogicalProgram):
        raise ValueError("logical program compiler input must be LogicalProgram")
    diagnostics = _validate_logical_lowering(program)
    if diagnostics:
        raise CompileError(tuple(diagnostics))

    logical_allocation = _allocate_logical_program(program)
    slots = {
        entry.logical_qubit_id: entry.slot
        for entry in logical_allocation.entries
    }
    operations = tuple(
        _lower_logical_instruction(instruction, slots)
        for instruction in program.instructions
    )
    return LogicalCompilationResult(
        ir=CircuitIR(
            program.id,
            program.name,
            logical_allocation.allocated_qubit_count,
            operations,
        ),
        logical_allocation=logical_allocation,
        readout=_build_readout_plan(program, slots),
    )


def compile_logical_module(module: LogicalModule) -> LogicalCompilationResult:
    """Expand calls before analyzing, allocating, and lowering logical values."""

    if not isinstance(module, LogicalModule):
        raise ValueError("logical module compiler input must be LogicalModule")
    diagnostics = _validate_logical_module_lowering(module)
    if diagnostics:
        raise CompileError(tuple(diagnostics))

    expanded_program = expand_logical_module(module)
    lifetime_analysis = analyze_logical_lifetimes(expanded_program)
    logical_allocation = _allocate_expanded_program(
        expanded_program,
        lifetime_analysis,
    )
    slots = {
        entry.logical_qubit_id: entry.slot
        for entry in logical_allocation.entries
    }
    operations = tuple(
        _lower_expanded_logical_instruction(instruction, slots)
        for instruction in expanded_program.instructions
    )
    return LogicalCompilationResult(
        ir=CircuitIR(
            expanded_program.id,
            expanded_program.name,
            logical_allocation.allocated_qubit_count,
            operations,
        ),
        logical_allocation=logical_allocation,
        readout=_build_expanded_readout_plan(expanded_program, slots),
        expanded_program=expanded_program,
        call_expansion=expanded_program.call_expansion,
        lifetime_analysis=lifetime_analysis,
    )


def _validate(program: Program) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    if program.qubit_count <= 0:
        diagnostics.append(Diagnostic("A100", "program must declare at least one qubit"))

    for index, operation in enumerate(program.operations):
        all_qubits = operation.controls + operation.targets
        for qubit in all_qubits:
            if not isinstance(qubit, int):
                diagnostics.append(
                    _operation_diagnostic(
                        program,
                        index,
                        operation,
                        "A101",
                        f"qubit reference must be an integer: {qubit!r}",
                    )
                )
            elif qubit < 0 or qubit >= program.qubit_count:
                diagnostics.append(
                    _operation_diagnostic(
                        program,
                        index,
                        operation,
                        "A102",
                        f"qubit {qubit} is outside program width {program.qubit_count}",
                    )
                )
        if operation.name == "cx" and operation.controls == operation.targets:
            diagnostics.append(
                _operation_diagnostic(
                    program,
                    index,
                    operation,
                    "A103",
                    "controlled-X requires distinct control and target qubits",
                )
            )
        if operation.name not in _OPCODE_MAP:
            diagnostics.append(
                _operation_diagnostic(
                    program,
                    index,
                    operation,
                    "A104",
                    f"unsupported operation {operation.name!r}",
                )
            )
        elif operation.name in _ROTATION_NAMES and not isinstance(
            operation.angle,
            Angle,
        ):
            diagnostics.append(
                _operation_diagnostic(
                    program,
                    index,
                    operation,
                    "A105",
                    f"{operation.name.upper()} expects an angle. "
                    "Use rad(2) or deg(2).",
                )
            )
    return diagnostics


def _validate_logical_lowering(program: LogicalProgram) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    has_observation = False
    for index, instruction in enumerate(program.instructions):
        if isinstance(instruction, (LogicalGateOperation, LogicalRotationOperation)):
            if has_observation:
                diagnostics.append(
                    _logical_instruction_diagnostic(
                        index,
                        instruction,
                        "A202",
                        "exact state-vector execution supports terminal observations only",
                    )
                )
            if (
                isinstance(instruction, LogicalGateOperation)
                and instruction.opcode not in _LOGICAL_GATE_OPCODE_MAP
            ):
                diagnostics.append(
                    _logical_instruction_diagnostic(
                        index,
                        instruction,
                        "A200",
                        f"logical gate {instruction.opcode.value!r} has no supported lowering",
                    )
                )
        elif isinstance(instruction, LogicalCallOperation):
            diagnostics.append(
                _logical_instruction_diagnostic(
                    index,
                    instruction,
                    "A203",
                    "logical calls require compilation through compile_logical_module",
                )
            )
        else:
            has_observation = True
            if instruction.basis.name != _Z_BASIS_NAME:
                diagnostics.append(
                    _logical_instruction_diagnostic(
                        index,
                        instruction,
                        "A201",
                        "only z-basis observations are supported by logical allocation lowering; "
                        f"received {instruction.basis.name!r}",
                    )
                )
    return diagnostics


def _validate_logical_module_lowering(module: LogicalModule) -> list[Diagnostic]:
    """Validate the flattened execution shape without allocating during traversal."""

    diagnostics: list[Diagnostic] = []
    programs_by_id = {program.id: program for program in module.programs}
    for caller in module.programs:
        for index, instruction in enumerate(caller.instructions):
            if not isinstance(instruction, LogicalCallOperation):
                continue
            callee = programs_by_id[instruction.callee_program_id]
            if any(isinstance(item, Observation) for item in callee.instructions):
                diagnostics.append(
                    _logical_instruction_diagnostic(
                        index,
                        instruction,
                        "A204",
                        "composed quantum callees cannot contain observations",
                    )
                )
    if diagnostics:
        return diagnostics

    expanded = expand_logical_module(module)
    has_observation = False
    for index, expanded_instruction in enumerate(expanded.instructions):
        instruction = expanded_instruction.instruction
        if isinstance(instruction, (LogicalGateOperation, LogicalRotationOperation)):
            if has_observation:
                diagnostics.append(
                    _logical_instruction_diagnostic(
                        index,
                        instruction,
                        "A202",
                        "exact state-vector execution supports terminal observations only",
                    )
                )
            if (
                isinstance(instruction, LogicalGateOperation)
                and instruction.opcode not in _LOGICAL_GATE_OPCODE_MAP
            ):
                diagnostics.append(
                    _logical_instruction_diagnostic(
                        index,
                        instruction,
                        "A200",
                        f"logical gate {instruction.opcode.value!r} has no supported lowering",
                    )
                )
            if (
                isinstance(instruction, LogicalGateOperation)
                and instruction.opcode is LogicalGateOpCode.CX
                and instruction.controls == instruction.targets
            ):
                diagnostics.append(
                    _logical_instruction_diagnostic(
                        index,
                        instruction,
                        "A205",
                        "logical call bindings cannot lower CX control and target to the same "
                        "value",
                    )
                )
            continue
        has_observation = True
        if instruction.basis.name != _Z_BASIS_NAME:
            diagnostics.append(
                _logical_instruction_diagnostic(
                    index,
                    instruction,
                    "A201",
                    "only z-basis observations are supported by logical allocation lowering; "
                    f"received {instruction.basis.name!r}",
                )
            )
    return diagnostics


def _lower(program: Program, operation: SourceOperation) -> Operation:
    source = _source_ref(program, operation)
    angle_radians = None
    angle_metadata = None
    if operation.name in _ROTATION_NAMES:
        angle = operation.angle
        if not isinstance(angle, Angle):  # pragma: no cover - validated before lowering
            raise RuntimeError("rotation lowering requires an explicit Angle")
        angle_radians = angle.radians
        angle_metadata = AngleMetadata(angle.source_value, angle.source_unit.value)
    return Operation(
        opcode=_OPCODE_MAP[operation.name],
        targets=operation.targets,
        id=make_ir_operation_id(source, "source-lowering", 0),
        controls=operation.controls,
        key=operation.key,
        source=source,
        angle_radians=angle_radians,
        angle_metadata=angle_metadata,
    )


def _allocate_logical_program(program: LogicalProgram) -> LogicalSlotAllocationPlan:
    entries = tuple(
        LogicalSlotAllocationEntry(qubit.id, qubit.display_name, slot)
        for slot, qubit in enumerate(program.qubits)
    )
    return LogicalSlotAllocationPlan(
        policy_name=LOGICAL_ALLOCATION_POLICY_NAME,
        entries=entries,
        peak_live_qubits=len(entries),
        allocated_qubit_count=len(entries),
    )


def _allocate_expanded_program(
    program: ExpandedLogicalProgram,
    lifetimes: LogicalLifetimeAnalysis,
) -> LogicalSlotAllocationPlan:
    entries = tuple(
        LogicalSlotAllocationEntry(
            logical_qubit_id=qubit.id,
            display_name=qubit.display_name,
            slot=slot,
            origin=qubit.origin,
        )
        for slot, qubit in enumerate(program.qubits)
    )
    return LogicalSlotAllocationPlan(
        policy_name=EXPANDED_LOGICAL_ALLOCATION_POLICY_NAME,
        entries=entries,
        peak_live_qubits=lifetimes.peak_live_logical_values,
        allocated_qubit_count=len(entries),
    )


def _build_readout_plan(
    program: LogicalProgram,
    slots: dict[LogicalQubitId, int],
) -> ReadoutPlan:
    result_values = {result.id: result for result in program.classical_bits}
    observations = tuple(
        AllocatedObservation(
            result_id=instruction.result_id,
            result_display_name=result_values[instruction.result_id].display_name,
            logical_qubit_id=instruction.qubit_id,
            allocated_slot=slots[instruction.qubit_id],
            basis=instruction.basis,
            reason=instruction.reason,
            logical_operation_id=instruction.id,
        )
        for instruction in program.instructions
        if isinstance(instruction, Observation)
    )
    return ReadoutPlan(observations=observations, return_shape=program.return_shape)


def _build_expanded_readout_plan(
    program: ExpandedLogicalProgram,
    slots: dict[LogicalQubitId, int],
) -> ReadoutPlan:
    result_values = {result.id: result for result in program.classical_bits}
    observations = tuple(
        AllocatedObservation(
            result_id=instruction.result_id,
            result_display_name=result_values[instruction.result_id].display_name,
            logical_qubit_id=instruction.qubit_id,
            allocated_slot=slots[instruction.qubit_id],
            basis=instruction.basis,
            reason=instruction.reason,
            logical_operation_id=expanded_instruction.definition_operation_id,
        )
        for expanded_instruction in program.instructions
        if isinstance((instruction := expanded_instruction.instruction), Observation)
    )
    return ReadoutPlan(observations=observations, return_shape=program.return_shape)


def _lower_expanded_logical_instruction(
    expanded_instruction: ExpandedLogicalInstruction,
    slots: dict[LogicalQubitId, int],
) -> Operation:
    call_path = tuple(frame.call_operation_id for frame in expanded_instruction.call_stack)
    operation_id = (
        make_invoked_logical_ir_operation_id(
            call_path,
            expanded_instruction.definition_operation_id,
            _LOGICAL_LOWERING_TRANSFORMATION,
            0,
        )
        if call_path
        else make_logical_ir_operation_id(
            expanded_instruction.definition_operation_id,
            _LOGICAL_LOWERING_TRANSFORMATION,
            0,
        )
    )
    return _lower_logical_instruction(
        expanded_instruction.instruction,
        slots,
        ir_operation_id=operation_id,
        call_stack=expanded_instruction.call_stack,
        definition_logical_operation_id=expanded_instruction.definition_operation_id,
    )


def _lower_logical_instruction(
    instruction: LogicalGateOperation | LogicalRotationOperation | Observation,
    slots: dict[LogicalQubitId, int],
    *,
    ir_operation_id: IrOperationId | None = None,
    call_stack: tuple[CallFrameProvenance, ...] = (),
    definition_logical_operation_id: LogicalOperationId | None = None,
) -> Operation:
    if isinstance(instruction, LogicalGateOperation):
        opcode = _LOGICAL_GATE_OPCODE_MAP[instruction.opcode]
        targets = tuple(slots[qubit_id] for qubit_id in instruction.targets)
        controls = tuple(slots[qubit_id] for qubit_id in instruction.controls)
        if opcode is OpCode.CX and controls == targets:
            raise RuntimeError("logical CX lowering requires distinct control and target slots")
        key = None
        observation = None
        angle_radians = None
        angle_metadata = None
    elif isinstance(instruction, LogicalRotationOperation):
        opcode = _LOGICAL_ROTATION_OPCODE_MAP[instruction.axis]
        targets = (slots[instruction.target],)
        controls = ()
        key = None
        observation = None
        angle_radians = instruction.angle.radians
        angle_metadata = AngleMetadata(
            instruction.angle.source_value,
            instruction.angle.source_unit.value,
        )
    else:
        opcode = OpCode.MEASURE
        targets = (slots[instruction.qubit_id],)
        controls = ()
        key = str(instruction.result_id)
        angle_radians = None
        angle_metadata = None
        observation = ObservationMetadata(
            logical_qubit_id=instruction.qubit_id,
            result_id=instruction.result_id,
            basis_name=instruction.basis.name,
            reason=instruction.reason.value,
        )
    source = instruction.source
    parent_source_ids = (source.source_operation_id,) if source is not None else ()
    definition_operation_id = definition_logical_operation_id or instruction.id
    return Operation(
        opcode=opcode,
        targets=targets,
        id=ir_operation_id
        or make_logical_ir_operation_id(
            instruction.id,
            _LOGICAL_LOWERING_TRANSFORMATION,
            0,
        ),
        controls=controls,
        key=key,
        source=source,
        provenance=OperationProvenance(
            parent_source_ids=parent_source_ids,
            transformation=_LOGICAL_LOWERING_TRANSFORMATION,
            parent_logical_operation_ids=(definition_operation_id,),
            call_stack=call_stack,
        ),
        observation=observation,
        angle_radians=angle_radians,
        angle_metadata=angle_metadata,
    )


def _operation_diagnostic(
    program: Program,
    index: int,
    operation: SourceOperation,
    code: str,
    message: str,
) -> Diagnostic:
    return Diagnostic(code, message, index, _source_ref(program, operation))


def _logical_instruction_diagnostic(
    index: int,
    instruction: (
        LogicalGateOperation | LogicalRotationOperation | Observation | LogicalCallOperation
    ),
    code: str,
    message: str,
) -> Diagnostic:
    return Diagnostic(
        code,
        message,
        index,
        instruction.source,
        logical_operation_id=instruction.id,
    )


def make_ir_operation_id(
    source: SourceRef,
    transformation: str,
    output_index: int,
) -> IrOperationId:
    return _make_ir_operation_id(
        source.source_operation_id,
        transformation,
        output_index,
    )


def make_logical_ir_operation_id(
    logical_operation_id: LogicalOperationId,
    transformation: str,
    output_index: int,
) -> IrOperationId:
    """Create an IR ID from semantic instruction identity rather than source IDs."""

    return _make_ir_operation_id(logical_operation_id, transformation, output_index)


def make_invoked_logical_ir_operation_id(
    call_path: tuple[LogicalOperationId, ...],
    logical_operation_id: LogicalOperationId,
    transformation: str,
    output_index: int,
) -> IrOperationId:
    """Create a deterministic IR ID for one callee operation at one invocation path."""

    if not isinstance(call_path, tuple) or not call_path:
        raise ValueError("invoked logical IR operation IDs require a non-empty call path")
    for call_operation_id in call_path:
        require_nonempty_identifier(
            call_operation_id,
            label="invoked logical IR call operation ID",
        )
    require_nonempty_identifier(
        logical_operation_id,
        label="invoked logical IR operation ID",
    )
    invocation_identity = ":invoke:".join((*call_path, logical_operation_id))
    return _make_ir_operation_id(invocation_identity, transformation, output_index)


def _make_ir_operation_id(
    parent_operation_id: str,
    transformation: str,
    output_index: int,
) -> IrOperationId:
    require_nonempty_identifier(parent_operation_id, label="IR parent operation ID")
    require_nonempty_identifier(transformation, label="IR transformation")
    if not isinstance(output_index, int) or output_index < 0:
        raise ValueError("IR transformation output index must be a non-negative integer")
    return IrOperationId(
        f"{parent_operation_id}:daidalon:{transformation}:{output_index}"
    )


def _source_ref(program: Program, operation: SourceOperation) -> SourceRef:
    return SourceRef.from_range(
        program_id=program.id,
        source_range=operation.source_range,
        source_operation_id=SourceOperationId(operation.id),
        snapshot_operation_id=operation.id,
        source_node_id=operation.source_node_id,
    )


def _require_nonnegative_int(value: object, *, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
