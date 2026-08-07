from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from ariadion_core import (
	CallInstanceId,
	ClassicalBitId,
	LogicalOperationId,
	LogicalQubitId,
	ProgramId,
	SourceRef,
	canonical_json,
	require_nonempty_identifier,
)
from ariadion_ir import CallFrameProvenance
from ariadion_semantics import (
	LogicalCallOperation,
	LogicalGateOperation,
	LogicalModule,
	LogicalProgram,
	LogicalQubitValue,
	LogicalRotationOperation,
	NoneReturn,
	Observation,
	ObservationResultValue,
	QuantumArgumentBinding,
	ReturnShape,
	ReturnValueKind,
	ReturnValueRef,
	ScalarReturn,
	TupleReturn,
	return_value_refs,
)


_ExpandedInstruction = LogicalGateOperation | LogicalRotationOperation | Observation
_ResolveValue = Callable[[LogicalQubitId], LogicalQubitId]


@dataclass(frozen=True, slots=True)
class LogicalQubitOrigin:
	"""The reusable definition that produced one expanded logical quantum value."""

	definition_program_id: ProgramId
	definition_qubit_id: LogicalQubitId
	call_instance_id: CallInstanceId | None

	def __post_init__(self) -> None:
		require_nonempty_identifier(
			self.definition_program_id,
			label="logical qubit origin definition program ID",
		)
		require_nonempty_identifier(
			self.definition_qubit_id,
			label="logical qubit origin definition qubit ID",
		)
		if self.call_instance_id is not None:
			require_nonempty_identifier(
				self.call_instance_id,
				label="logical qubit origin call instance ID",
			)

	def to_dict(self) -> dict[str, str | None]:
		return {
			"definition_program_id": self.definition_program_id,
			"definition_qubit_id": self.definition_qubit_id,
			"call_instance_id": self.call_instance_id,
		}

	def to_json(self) -> str:
		return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class ExpandedLogicalQubit:
	"""One invocation-specific quantum value before physical slot allocation."""

	id: LogicalQubitId
	display_name: str | None
	origin: LogicalQubitOrigin
	source: SourceRef | None
	creation_instruction_index: int

	def __post_init__(self) -> None:
		require_nonempty_identifier(self.id, label="expanded logical qubit ID")
		if self.display_name is not None:
			require_nonempty_identifier(
				self.display_name,
				label="expanded logical qubit display name",
			)
		if not isinstance(self.origin, LogicalQubitOrigin):
			raise ValueError("expanded logical qubit origin must be LogicalQubitOrigin")
		if self.source is not None and not isinstance(self.source, SourceRef):
			raise ValueError("expanded logical qubit source must be SourceRef")
		if (
			isinstance(self.creation_instruction_index, bool)
			or not isinstance(self.creation_instruction_index, int)
			or self.creation_instruction_index < 0
		):
			raise ValueError(
				"expanded logical qubit creation_instruction_index must be non-negative"
			)
		if self.origin.call_instance_id is None and self.id != self.origin.definition_qubit_id:
			raise ValueError(
				"root expanded logical qubit ID must equal its definition qubit ID"
			)

	def to_dict(self) -> dict[str, object]:
		return {
			"id": self.id,
			"display_name": self.display_name,
			"origin": self.origin.to_dict(),
			"source": self.source.to_dict() if self.source is not None else None,
			"creation_instruction_index": self.creation_instruction_index,
		}

	def to_json(self) -> str:
		return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class ExpandedLogicalInstruction:
	"""One non-call semantic instruction after aliases and invocations are resolved."""

	id: LogicalOperationId
	instruction: _ExpandedInstruction
	definition_operation_id: LogicalOperationId
	call_stack: tuple[CallFrameProvenance, ...] = ()

	def __post_init__(self) -> None:
		require_nonempty_identifier(self.id, label="expanded logical instruction ID")
		if not isinstance(
			self.instruction,
			(LogicalGateOperation, LogicalRotationOperation, Observation),
		):
			raise ValueError(
				"expanded logical instruction must wrap a gate, rotation, or observation"
			)
		if self.instruction.id != self.id:
			raise ValueError("expanded logical instruction ID must match its instruction ID")
		require_nonempty_identifier(
			self.definition_operation_id,
			label="expanded logical instruction definition operation ID",
		)
		if not isinstance(self.call_stack, tuple) or not all(
			isinstance(frame, CallFrameProvenance) for frame in self.call_stack
		):
			raise ValueError(
				"expanded logical instruction call_stack must contain CallFrameProvenance values"
			)

	def to_dict(self) -> dict[str, object]:
		return {
			"id": self.id,
			"instruction": self.instruction.to_dict(),
			"definition_operation_id": self.definition_operation_id,
			"call_stack": [frame.to_dict() for frame in self.call_stack],
		}

	def to_json(self) -> str:
		return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class CallExpansionRecord:
	"""Evidence for one instantiated semantic call within an expanded module."""

	call_instance_id: CallInstanceId
	caller_program_id: ProgramId
	callee_program_id: ProgramId
	call_operation_id: LogicalOperationId
	parameter_bindings: tuple[QuantumArgumentBinding, ...]
	instantiated_local_qubits: tuple[LogicalQubitId, ...]
	expanded_instruction_ids: tuple[LogicalOperationId, ...]
	returned_logical_qubit_id: LogicalQubitId | None = None
	call_source: SourceRef | None = None

	def __post_init__(self) -> None:
		require_nonempty_identifier(self.call_instance_id, label="call expansion instance ID")
		require_nonempty_identifier(
			self.caller_program_id,
			label="call expansion caller program ID",
		)
		require_nonempty_identifier(
			self.callee_program_id,
			label="call expansion callee program ID",
		)
		require_nonempty_identifier(
			self.call_operation_id,
			label="call expansion operation ID",
		)
		if not isinstance(self.parameter_bindings, tuple) or not all(
			isinstance(binding, QuantumArgumentBinding) for binding in self.parameter_bindings
		):
			raise ValueError(
				"call expansion parameter_bindings must contain QuantumArgumentBinding values"
			)
		_validate_logical_qubit_ids(
			self.instantiated_local_qubits,
			label="call expansion instantiated local qubits",
			allow_empty=True,
		)
		_validate_logical_operation_ids(
			self.expanded_instruction_ids,
			label="call expansion expanded instruction IDs",
			allow_empty=True,
		)
		if self.returned_logical_qubit_id is not None:
			require_nonempty_identifier(
				self.returned_logical_qubit_id,
				label="call expansion returned logical qubit ID",
			)
		if self.call_source is not None:
			if not isinstance(self.call_source, SourceRef):
				raise ValueError("call expansion source must be SourceRef")
			if self.call_source.program_id != self.caller_program_id:
				raise ValueError(
					"call expansion source program ID must match its caller program ID"
				)

	def to_dict(self) -> dict[str, object]:
		return {
			"call_instance_id": self.call_instance_id,
			"caller_program_id": self.caller_program_id,
			"callee_program_id": self.callee_program_id,
			"call_operation_id": self.call_operation_id,
			"parameter_bindings": [binding.to_dict() for binding in self.parameter_bindings],
			"instantiated_local_qubits": list(self.instantiated_local_qubits),
			"expanded_instruction_ids": list(self.expanded_instruction_ids),
			"returned_logical_qubit_id": self.returned_logical_qubit_id,
			"call_source": self.call_source.to_dict() if self.call_source is not None else None,
		}

	def to_json(self) -> str:
		return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class CallExpansionPlan:
	"""Ordered, immutable evidence of every call materialized in one module."""

	records: tuple[CallExpansionRecord, ...] = ()

	def __post_init__(self) -> None:
		if not isinstance(self.records, tuple) or not all(
			isinstance(record, CallExpansionRecord) for record in self.records
		):
			raise ValueError("call expansion records must contain CallExpansionRecord values")
		call_instance_ids = tuple(record.call_instance_id for record in self.records)
		if len(call_instance_ids) != len(set(call_instance_ids)):
			raise ValueError("call expansion call instance IDs must be unique")

	def to_dict(self) -> dict[str, object]:
		return {"records": [record.to_dict() for record in self.records]}

	def to_json(self) -> str:
		return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class ExpandedLogicalProgram:
	"""Invocation-aware logical semantics before lifetime analysis or allocation."""

	id: ProgramId
	name: str
	qubits: tuple[ExpandedLogicalQubit, ...]
	instructions: tuple[ExpandedLogicalInstruction, ...]
	classical_bits: tuple[ObservationResultValue, ...]
	return_shape: ReturnShape
	call_expansion: CallExpansionPlan
	call_escape_qubit_ids: tuple[LogicalQubitId, ...] = ()

	def __post_init__(self) -> None:
		require_nonempty_identifier(self.id, label="expanded logical program ID")
		require_nonempty_identifier(self.name, label="expanded logical program name")
		if not isinstance(self.qubits, tuple) or not all(
			isinstance(qubit, ExpandedLogicalQubit) for qubit in self.qubits
		):
			raise ValueError("expanded logical program qubits must contain ExpandedLogicalQubit values")
		if not isinstance(self.instructions, tuple) or not all(
			isinstance(instruction, ExpandedLogicalInstruction)
			for instruction in self.instructions
		):
			raise ValueError(
				"expanded logical program instructions must contain ExpandedLogicalInstruction values"
			)
		if not isinstance(self.classical_bits, tuple) or not all(
			isinstance(bit, ObservationResultValue) for bit in self.classical_bits
		):
			raise ValueError(
				"expanded logical program classical_bits must contain ObservationResultValue values"
			)
		if not isinstance(self.return_shape, (ScalarReturn, TupleReturn, NoneReturn)):
			raise ValueError("expanded logical program return_shape must be a ReturnShape")
		if not isinstance(self.call_expansion, CallExpansionPlan):
			raise ValueError("expanded logical program call_expansion must be CallExpansionPlan")

		qubit_ids = tuple(qubit.id for qubit in self.qubits)
		_require_unique(qubit_ids, label="expanded logical program qubit IDs")
		instruction_ids = tuple(instruction.id for instruction in self.instructions)
		_require_unique(instruction_ids, label="expanded logical program instruction IDs")
		classical_bit_ids = tuple(bit.id for bit in self.classical_bits)
		_require_unique(classical_bit_ids, label="expanded logical program classical bit IDs")
		known_qubit_ids = set(qubit_ids)
		known_classical_bit_ids = set(classical_bit_ids)

		observed_result_ids: set[ClassicalBitId] = set()
		observed_qubit_ids: set[LogicalQubitId] = set()
		for expanded_instruction in self.instructions:
			instruction = expanded_instruction.instruction
			if isinstance(instruction, LogicalGateOperation):
				referenced_qubits = instruction.controls + instruction.targets
			elif isinstance(instruction, LogicalRotationOperation):
				referenced_qubits = (instruction.target,)
			else:
				referenced_qubits = (instruction.qubit_id,)
				observed_qubit_ids.add(instruction.qubit_id)
				observed_result_ids.add(instruction.result_id)
				if instruction.result_id not in known_classical_bit_ids:
					raise ValueError(
						"expanded observation references an undeclared classical bit: "
						f"{instruction.result_id}"
					)
			for qubit_id in referenced_qubits:
				if qubit_id not in known_qubit_ids:
					raise ValueError(
						"expanded instruction references an undeclared logical quantum value: "
						f"{qubit_id}"
					)

		for reference in return_value_refs(self.return_shape):
			if reference.kind is ReturnValueKind.CLASSICAL_BIT:
				if reference.value_id not in known_classical_bit_ids:
					raise ValueError(
						"expanded classical return references an undeclared observation result: "
						f"{reference.value_id}"
					)
				if reference.value_id not in observed_result_ids:
					raise ValueError(
						"expanded classical return must have an observation producer: "
						f"{reference.value_id}"
					)
			elif reference.kind is ReturnValueKind.QUANTUM_VALUE:
				if reference.value_id not in known_qubit_ids:
					raise ValueError(
						"expanded quantum return references an undeclared logical quantum value: "
						f"{reference.value_id}"
					)
				if reference.value_id in observed_qubit_ids:
					raise ValueError(
						"expanded quantum return cannot reference an observed logical value: "
						f"{reference.value_id}"
					)
			else:  # pragma: no cover - protects future enum expansion
				raise ValueError(f"unsupported return value kind: {reference.kind}")

		_validate_logical_qubit_ids(
			self.call_escape_qubit_ids,
			label="expanded logical program call escape qubit IDs",
			allow_empty=True,
		)
		_require_unique(
			self.call_escape_qubit_ids,
			label="expanded logical program call escape qubit IDs",
		)
		if any(qubit_id not in known_qubit_ids for qubit_id in self.call_escape_qubit_ids):
			raise ValueError(
				"expanded logical program call escape values must be declared logical values"
			)

	def to_dict(self) -> dict[str, object]:
		return {
			"id": self.id,
			"name": self.name,
			"qubits": [qubit.to_dict() for qubit in self.qubits],
			"instructions": [instruction.to_dict() for instruction in self.instructions],
			"classical_bits": [bit.to_dict() for bit in self.classical_bits],
			"return_shape": self.return_shape.to_dict(),
			"call_expansion": self.call_expansion.to_dict(),
			"call_escape_qubit_ids": list(self.call_escape_qubit_ids),
		}

	def to_json(self) -> str:
		return canonical_json(self.to_dict())


class LogicalLifetimeEndReason(str, Enum):
	"""The conservative endpoint selected for one expanded logical value."""

	LAST_USE = "last_use"
	RETURNED = "returned"
	CALL_ESCAPE = "call_escape"
	PROGRAM_END = "program_end"


@dataclass(frozen=True, slots=True)
class LogicalLifetime:
	"""An inclusive instruction-index interval for one expanded logical value."""

	logical_qubit_id: LogicalQubitId
	first_instruction_index: int
	last_instruction_index: int
	end_reason: LogicalLifetimeEndReason

	def __post_init__(self) -> None:
		require_nonempty_identifier(self.logical_qubit_id, label="logical lifetime qubit ID")
		for value, label in (
			(self.first_instruction_index, "logical lifetime first_instruction_index"),
			(self.last_instruction_index, "logical lifetime last_instruction_index"),
		):
			if isinstance(value, bool) or not isinstance(value, int) or value < 0:
				raise ValueError(f"{label} must be a non-negative integer")
		if self.last_instruction_index < self.first_instruction_index:
			raise ValueError(
				"logical lifetime last_instruction_index must not precede first_instruction_index"
			)
		if not isinstance(self.end_reason, LogicalLifetimeEndReason):
			raise ValueError("logical lifetime end_reason must be LogicalLifetimeEndReason")

	def to_dict(self) -> dict[str, object]:
		return {
			"logical_qubit_id": self.logical_qubit_id,
			"first_instruction_index": self.first_instruction_index,
			"last_instruction_index": self.last_instruction_index,
			"end_reason": self.end_reason.value,
		}

	def to_json(self) -> str:
		return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class LogicalLifetimeAnalysis:
	"""Conservative lifetime evidence for one expanded logical program."""

	lifetimes: tuple[LogicalLifetime, ...]
	peak_live_logical_values: int

	def __post_init__(self) -> None:
		if not isinstance(self.lifetimes, tuple) or not all(
			isinstance(lifetime, LogicalLifetime) for lifetime in self.lifetimes
		):
			raise ValueError("logical lifetime analysis lifetimes must contain LogicalLifetime values")
		lifetime_ids = tuple(lifetime.logical_qubit_id for lifetime in self.lifetimes)
		_require_unique(lifetime_ids, label="logical lifetime analysis qubit IDs")
		if (
			isinstance(self.peak_live_logical_values, bool)
			or not isinstance(self.peak_live_logical_values, int)
			or self.peak_live_logical_values < 0
		):
			raise ValueError(
				"logical lifetime analysis peak_live_logical_values must be non-negative"
			)
		if self.peak_live_logical_values > len(self.lifetimes):
			raise ValueError(
				"logical lifetime analysis peak cannot exceed declared lifetimes"
			)

	def to_dict(self) -> dict[str, object]:
		return {
			"lifetimes": [lifetime.to_dict() for lifetime in self.lifetimes],
			"peak_live_logical_values": self.peak_live_logical_values,
		}

	def to_json(self) -> str:
		return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class _ProgramExpansionResult:
	return_shape: ReturnShape
	instantiated_local_qubits: tuple[LogicalQubitId, ...]


class _LogicalModuleExpander:
	def __init__(self, module: LogicalModule) -> None:
		self.module = module
		self.programs_by_id = {program.id: program for program in module.programs}
		self.qubits: list[ExpandedLogicalQubit] = []
		self.instructions: list[ExpandedLogicalInstruction] = []
		self.records: list[CallExpansionRecord | None] = []
		self.call_escape_qubit_ids: list[LogicalQubitId] = []

	def expand(self) -> ExpandedLogicalProgram:
		entry = self.module.entry_program
		result = self._expand_program(
			entry,
			parameter_bindings={},
			call_stack=(),
			call_instance_id=None,
		)
		if any(record is None for record in self.records):  # pragma: no cover
			raise RuntimeError("call expansion did not complete every call record")
		records = tuple(record for record in self.records if record is not None)
		return ExpandedLogicalProgram(
			id=entry.id,
			name=entry.name,
			qubits=tuple(self.qubits),
			instructions=tuple(self.instructions),
			classical_bits=entry.classical_bits,
			return_shape=result.return_shape,
			call_expansion=CallExpansionPlan(records),
			call_escape_qubit_ids=_unique_in_order(self.call_escape_qubit_ids),
		)

	def _expand_program(
		self,
		program: LogicalProgram,
		*,
		parameter_bindings: dict[LogicalQubitId, LogicalQubitId],
		call_stack: tuple[CallFrameProvenance, ...],
		call_instance_id: CallInstanceId | None,
	) -> _ProgramExpansionResult:
		parameter_ids = {parameter.logical_qubit_id for parameter in program.parameters}
		definitions_by_id = {qubit.id: qubit for qubit in program.qubits}
		value_bindings = dict(parameter_bindings)
		instantiated_local_qubits: list[LogicalQubitId] = []

		for parameter in program.parameters:
			if parameter.logical_qubit_id in value_bindings:
				continue
			if call_instance_id is not None:
				raise ValueError(
					"expanded callee parameters must resolve to caller logical values"
				)
			value_bindings[parameter.logical_qubit_id] = self._instantiate_definition(
				program,
				definitions_by_id[parameter.logical_qubit_id],
				call_instance_id,
			)

		pending_definitions = [
			qubit for qubit in program.qubits if qubit.id not in parameter_ids
		]
		pending_definitions.sort(key=lambda qubit: _source_position(qubit.source))

		def instantiate_definition(qubit: LogicalQubitValue) -> LogicalQubitId:
			expanded_id = value_bindings.get(qubit.id)
			if expanded_id is not None:
				return expanded_id
			expanded_id = self._instantiate_definition(program, qubit, call_instance_id)
			value_bindings[qubit.id] = expanded_id
			if call_instance_id is not None:
				instantiated_local_qubits.append(expanded_id)
			return expanded_id

		def resolve_value(value_id: LogicalQubitId) -> LogicalQubitId:
			expanded_id = value_bindings.get(value_id)
			if expanded_id is not None:
				return expanded_id
			definition = definitions_by_id.get(value_id)
			if definition is None:
				raise ValueError(
					"expanded logical instruction references an unresolved logical value: "
					f"{value_id}"
				)
			return instantiate_definition(definition)

		pending_index = 0
		for source_instruction in program.instructions:
			instruction_position = _source_position(source_instruction.source)
			while (
				pending_index < len(pending_definitions)
				and _source_position(pending_definitions[pending_index].source)
				<= instruction_position
			):
				instantiate_definition(pending_definitions[pending_index])
				pending_index += 1

			if isinstance(source_instruction, LogicalCallOperation):
				callee = self.programs_by_id[source_instruction.callee_program_id]
				resolved_parameters = {
					binding.parameter_id: resolve_value(binding.argument_id)
					for binding in source_instruction.arguments
				}
				child_call_instance_id = make_call_instance_id(
					entry_program_id=self.module.entry_program_id,
					parent_call_instance_id=call_instance_id,
					call_operation_id=source_instruction.id,
				)
				frame = CallFrameProvenance(
					caller_program_id=program.id,
					call_operation_id=source_instruction.id,
					callee_program_id=callee.id,
					call_source=source_instruction.source,
				)
				record_index = len(self.records)
				self.records.append(None)
				instruction_start = len(self.instructions)
				child_result = self._expand_program(
					callee,
					parameter_bindings=resolved_parameters,
					call_stack=call_stack + (frame,),
					call_instance_id=child_call_instance_id,
				)
				returned_logical_qubit_id = _scalar_quantum_return_id(
					child_result.return_shape
				)
				if source_instruction.result is not None:
					if returned_logical_qubit_id is None:
						raise ValueError(
							"logical call result binding requires a scalar quantum callee return"
						)
					value_bindings[source_instruction.result.caller_value_id] = (
						returned_logical_qubit_id
					)
					if self._was_instantiated_by(
						returned_logical_qubit_id,
						child_call_instance_id,
					):
						self.call_escape_qubit_ids.append(returned_logical_qubit_id)
				elif returned_logical_qubit_id is not None:
					raise ValueError(
						"logical call with a quantum return must provide a result binding"
					)
				self.records[record_index] = CallExpansionRecord(
					call_instance_id=child_call_instance_id,
					caller_program_id=program.id,
					callee_program_id=callee.id,
					call_operation_id=source_instruction.id,
					parameter_bindings=source_instruction.arguments,
					instantiated_local_qubits=child_result.instantiated_local_qubits,
					expanded_instruction_ids=tuple(
						instruction.id
						for instruction in self.instructions[instruction_start:]
					),
					returned_logical_qubit_id=returned_logical_qubit_id,
					call_source=source_instruction.source,
				)
				continue

			expanded_instruction_id = _expanded_instruction_id(
				source_instruction.id,
				call_instance_id,
			)
			expanded_instruction = _instantiate_instruction(
				source_instruction,
				expanded_instruction_id,
				resolve_value,
			)
			self.instructions.append(
				ExpandedLogicalInstruction(
					id=expanded_instruction_id,
					instruction=expanded_instruction,
					definition_operation_id=source_instruction.id,
					call_stack=call_stack,
				)
			)

		while pending_index < len(pending_definitions):
			instantiate_definition(pending_definitions[pending_index])
			pending_index += 1
		return _ProgramExpansionResult(
			return_shape=_resolve_return_shape(program.return_shape, resolve_value),
			instantiated_local_qubits=tuple(instantiated_local_qubits),
		)

	def _instantiate_definition(
		self,
		program: LogicalProgram,
		definition: LogicalQubitValue,
		call_instance_id: CallInstanceId | None,
	) -> LogicalQubitId:
		expanded_id = (
			definition.id
			if call_instance_id is None
			else LogicalQubitId(f"{call_instance_id}:qubit:{definition.id}")
		)
		self.qubits.append(
			ExpandedLogicalQubit(
				id=expanded_id,
				display_name=definition.display_name,
				origin=LogicalQubitOrigin(
					definition_program_id=program.id,
					definition_qubit_id=definition.id,
					call_instance_id=call_instance_id,
				),
				source=definition.source,
				creation_instruction_index=len(self.instructions),
			)
		)
		return expanded_id

	def _was_instantiated_by(
		self,
		logical_qubit_id: LogicalQubitId,
		call_instance_id: CallInstanceId,
	) -> bool:
		qubit = next(
			item for item in self.qubits if item.id == logical_qubit_id
		)
		origin_call_instance_id = qubit.origin.call_instance_id
		if origin_call_instance_id is None:
			return False
		return str(origin_call_instance_id).startswith(f"{call_instance_id}:call:") or (
			origin_call_instance_id == call_instance_id
		)


def expand_logical_module(module: LogicalModule) -> ExpandedLogicalProgram:
	"""Materialize an invocation-aware logical program without allocating slots."""

	if not isinstance(module, LogicalModule):
		raise ValueError("logical module expansion input must be LogicalModule")
	return _LogicalModuleExpander(module).expand()


def analyze_logical_lifetimes(
	program: ExpandedLogicalProgram,
) -> LogicalLifetimeAnalysis:
	"""Compute conservative expanded-value lifetimes without choosing slot reuse."""

	if not isinstance(program, ExpandedLogicalProgram):
		raise ValueError("logical lifetime analysis input must be ExpandedLogicalProgram")
	use_indexes = {qubit.id: [] for qubit in program.qubits}
	for index, expanded_instruction in enumerate(program.instructions):
		instruction = expanded_instruction.instruction
		if isinstance(instruction, LogicalGateOperation):
			references = instruction.controls + instruction.targets
		elif isinstance(instruction, LogicalRotationOperation):
			references = (instruction.target,)
		else:
			references = (instruction.qubit_id,)
		for qubit_id in references:
			use_indexes[qubit_id].append(index)

	returned_ids = {
		LogicalQubitId(reference.value_id)
		for reference in return_value_refs(program.return_shape)
		if reference.kind is ReturnValueKind.QUANTUM_VALUE
	}
	call_escape_ids = set(program.call_escape_qubit_ids)
	program_end_index = len(program.instructions)
	lifetimes: list[LogicalLifetime] = []
	for qubit in program.qubits:
		uses = use_indexes[qubit.id]
		first_index = min(uses) if uses else qubit.creation_instruction_index
		last_index = max(uses) if uses else qubit.creation_instruction_index
		if qubit.id in returned_ids:
			last_index = max(last_index, program_end_index)
			end_reason = LogicalLifetimeEndReason.RETURNED
		elif qubit.id in call_escape_ids:
			end_reason = LogicalLifetimeEndReason.CALL_ESCAPE
		elif qubit.origin.call_instance_id is None:
			last_index = max(last_index, program_end_index)
			end_reason = LogicalLifetimeEndReason.PROGRAM_END
		else:
			end_reason = LogicalLifetimeEndReason.LAST_USE
		lifetimes.append(
			LogicalLifetime(
				logical_qubit_id=qubit.id,
				first_instruction_index=first_index,
				last_instruction_index=last_index,
				end_reason=end_reason,
			)
		)

	peak_live_logical_values = max(
		(
			sum(
				lifetime.first_instruction_index <= index <= lifetime.last_instruction_index
				for lifetime in lifetimes
			)
			for index in range(program_end_index + 1)
		),
		default=0,
	)
	return LogicalLifetimeAnalysis(
		lifetimes=tuple(lifetimes),
		peak_live_logical_values=peak_live_logical_values,
	)


def make_call_instance_id(
	*,
	entry_program_id: ProgramId,
	parent_call_instance_id: CallInstanceId | None,
	call_operation_id: LogicalOperationId,
) -> CallInstanceId:
	"""Build an invocation ID from the complete ordered semantic call path."""

	require_nonempty_identifier(entry_program_id, label="call instance entry program ID")
	require_nonempty_identifier(call_operation_id, label="call instance operation ID")
	if parent_call_instance_id is None:
		return CallInstanceId(f"{entry_program_id}:call:{call_operation_id}")
	require_nonempty_identifier(
		parent_call_instance_id,
		label="call instance parent ID",
	)
	return CallInstanceId(f"{parent_call_instance_id}:call:{call_operation_id}")


def _instantiate_instruction(
	instruction: _ExpandedInstruction,
	expanded_instruction_id: LogicalOperationId,
	resolve_value: _ResolveValue,
) -> _ExpandedInstruction:
	if isinstance(instruction, LogicalGateOperation):
		return LogicalGateOperation(
			id=expanded_instruction_id,
			opcode=instruction.opcode,
			targets=tuple(resolve_value(target) for target in instruction.targets),
			controls=tuple(resolve_value(control) for control in instruction.controls),
			source=instruction.source,
		)
	if isinstance(instruction, LogicalRotationOperation):
		return LogicalRotationOperation(
			id=expanded_instruction_id,
			axis=instruction.axis,
			target=resolve_value(instruction.target),
			angle=instruction.angle,
			source=instruction.source,
		)
	return Observation(
		id=expanded_instruction_id,
		qubit_id=resolve_value(instruction.qubit_id),
		result_id=instruction.result_id,
		basis=instruction.basis,
		reason=instruction.reason,
		source=instruction.source,
	)


def _resolve_return_shape(
	return_shape: ReturnShape,
	resolve_value: _ResolveValue,
) -> ReturnShape:
	if isinstance(return_shape, NoneReturn):
		return return_shape
	if isinstance(return_shape, ScalarReturn):
		reference = return_shape.value
		value_id = (
			resolve_value(LogicalQubitId(reference.value_id))
			if reference.kind is ReturnValueKind.QUANTUM_VALUE
			else reference.value_id
		)
		return ScalarReturn(ReturnValueRef(reference.kind, value_id))
	return TupleReturn(
		tuple(_resolve_return_shape(item, resolve_value) for item in return_shape.items)
	)


def _scalar_quantum_return_id(return_shape: ReturnShape) -> LogicalQubitId | None:
	if not isinstance(return_shape, ScalarReturn):
		return None
	if return_shape.value.kind is not ReturnValueKind.QUANTUM_VALUE:
		return None
	return LogicalQubitId(return_shape.value.value_id)


def _expanded_instruction_id(
	definition_operation_id: LogicalOperationId,
	call_instance_id: CallInstanceId | None,
) -> LogicalOperationId:
	if call_instance_id is None:
		return definition_operation_id
	return LogicalOperationId(f"{call_instance_id}:operation:{definition_operation_id}")


def _source_position(source: SourceRef | None) -> tuple[int, str, int, int, str]:
	if source is None or source.source_range is None:
		return (1, "", 0, 0, str(source.source_operation_id) if source is not None else "")
	source_range = source.source_range
	return (
		0,
		source_range.file or "",
		source_range.line or 0,
		source_range.column or 0,
		str(source.source_operation_id),
	)


def _unique_in_order(values: list[LogicalQubitId]) -> tuple[LogicalQubitId, ...]:
	seen: set[LogicalQubitId] = set()
	ordered: list[LogicalQubitId] = []
	for value in values:
		if value not in seen:
			seen.add(value)
			ordered.append(value)
	return tuple(ordered)


def _require_unique(values: tuple[object, ...], *, label: str) -> None:
	if len(values) != len(set(values)):
		raise ValueError(f"{label} must be unique")


def _validate_logical_qubit_ids(
	value: tuple[LogicalQubitId, ...],
	*,
	label: str,
	allow_empty: bool,
) -> None:
	if not isinstance(value, tuple) or (not value and not allow_empty):
		expected = "a tuple" if allow_empty else "a non-empty tuple"
		raise ValueError(f"{label} must be {expected}")
	for qubit_id in value:
		require_nonempty_identifier(qubit_id, label=label)


def _validate_logical_operation_ids(
	value: tuple[LogicalOperationId, ...],
	*,
	label: str,
	allow_empty: bool,
) -> None:
	if not isinstance(value, tuple) or (not value and not allow_empty):
		expected = "a tuple" if allow_empty else "a non-empty tuple"
		raise ValueError(f"{label} must be {expected}")
	for operation_id in value:
		require_nonempty_identifier(operation_id, label=label)
