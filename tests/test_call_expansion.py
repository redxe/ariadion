from __future__ import annotations

import unittest

from ariadion import Bit, Qubit, cx, h, quantum, run, x, z
from ariadion_core import CallInstanceId
from ariadion_frontend_python import PythonFrontendError
from ariadion_semantics import LogicalCallOperation
from daidalon import (
    EXPANDED_LOGICAL_ALLOCATION_POLICY_NAME,
    LogicalLifetimeEndReason,
    analyze_logical_lifetimes,
    compile_logical_module,
    expand_logical_module,
)


@quantum
def _prepare() -> Qubit:
    value = Qubit()
    h(value)
    return value


@quantum
def _prepare_then_mark() -> Qubit:
    value = _prepare()
    z(value)
    return value


@quantum
def _prepare_then_alias() -> Qubit:
    value = _prepare()
    alias = value
    z(alias)
    return alias


@quantum
def _consume_prepared() -> None:
    value = _prepare()
    z(value)


@quantum
def _prepare_twice() -> tuple[Qubit, Qubit]:
    first = _prepare()
    second = _prepare()
    return first, second


@quantum
def _return_parameter(value: Qubit) -> Qubit:
    x(value)
    return value


@quantum
def _return_parameter_root() -> Qubit:
    input_value = Qubit()
    result = _return_parameter(input_value)
    return result


@quantum
def _consume_returned_parameter() -> None:
    input_value = Qubit()
    result = _return_parameter(input_value)
    z(result)


@quantum
def _scratch(value: Qubit) -> None:
    temporary = Qubit()
    h(temporary)
    cx(temporary, value)


@quantum
def _scratch_root() -> Qubit:
    output = Qubit()
    _scratch(output)
    return output


@quantum
def _forward_prepare() -> Qubit:
    value = _prepare()
    return value


@quantum
def _nested_prepare() -> Qubit:
    value = _forward_prepare()
    x(value)
    return value


@quantum
def _returns_bit() -> Bit:
    value = Qubit()
    return value


@quantum
def _returns_pair() -> tuple[Qubit, Qubit]:
    first = Qubit()
    second = Qubit()
    return first, second


@quantum
def _returns_none() -> None:
    value = Qubit()
    h(value)


@quantum
def _assigns_bit_result() -> None:
    value = _returns_bit()
    h(value)


@quantum
def _assigns_tuple_result() -> None:
    value = _returns_pair()
    h(value)


@quantum
def _assigns_none_result() -> None:
    value = _returns_none()
    h(value)


class CallExpansionTests(unittest.TestCase):
    def test_expansion_materializes_distinct_repeated_local_values(self) -> None:
        module = _prepare_twice.to_logical_module()
        first = expand_logical_module(module)
        second = expand_logical_module(module)

        self.assertEqual(first.to_json(), second.to_json())
        self.assertEqual(len(first.call_expansion.records), 2)
        first_record, second_record = first.call_expansion.records
        self.assertNotEqual(first_record.call_instance_id, second_record.call_instance_id)
        self.assertEqual(
            first_record.call_instance_id,
            CallInstanceId(
                f"{module.entry_program_id}:call:{first_record.call_operation_id}"
            ),
        )
        self.assertEqual(len(first_record.instantiated_local_qubits), 1)
        self.assertEqual(len(second_record.instantiated_local_qubits), 1)
        self.assertNotEqual(
            first_record.instantiated_local_qubits,
            second_record.instantiated_local_qubits,
        )

        first_local_id = first_record.instantiated_local_qubits[0]
        second_local_id = second_record.instantiated_local_qubits[0]
        locals_by_id = {qubit.id: qubit for qubit in first.qubits}
        self.assertEqual(
            locals_by_id[first_local_id].origin.definition_qubit_id,
            locals_by_id[second_local_id].origin.definition_qubit_id,
        )
        self.assertEqual(
            locals_by_id[first_local_id].origin.call_instance_id,
            first_record.call_instance_id,
        )
        self.assertEqual(
            locals_by_id[second_local_id].origin.call_instance_id,
            second_record.call_instance_id,
        )
        self.assertEqual(
            tuple(value.logical_qubit_id for value in run(_prepare_twice).returned_quantum_values),
            (first_local_id, second_local_id),
        )

    def test_scalar_quantum_call_results_are_aliases_not_new_states(self) -> None:
        program = _prepare_then_mark.to_logical_program()
        call = next(
            instruction
            for instruction in program.instructions
            if isinstance(instruction, LogicalCallOperation)
        )
        assert call.result is not None

        compilation = compile_logical_module(_prepare_then_mark.to_logical_module())
        expanded = compilation.expanded_program
        assert expanded is not None
        self.assertNotIn(
            call.result.caller_value_id,
            tuple(qubit.id for qubit in expanded.qubits),
        )
        self.assertEqual(len(expanded.qubits), 1)
        self.assertEqual(
            compilation.readout.quantum_return_ids(),
            (expanded.qubits[0].id,),
        )
        self.assertEqual(
            tuple(
                value.logical_qubit_id
                for value in run(_prepare_then_mark).returned_quantum_values
            ),
            (expanded.qubits[0].id,),
        )
        assert compilation.lifetime_analysis is not None
        lifetime = next(
            item
            for item in compilation.lifetime_analysis.lifetimes
            if item.logical_qubit_id == expanded.qubits[0].id
        )
        self.assertEqual(lifetime.first_instruction_index, 0)
        self.assertEqual(lifetime.last_instruction_index, 2)
        self.assertEqual(lifetime.end_reason, LogicalLifetimeEndReason.RETURNED)

    def test_aliasing_a_call_result_does_not_create_a_second_expanded_value(self) -> None:
        compilation = compile_logical_module(_prepare_then_alias.to_logical_module())
        expanded = compilation.expanded_program
        assert expanded is not None

        self.assertEqual(len(expanded.qubits), 1)
        self.assertEqual(
            tuple(
                value.logical_qubit_id
                for value in run(_prepare_then_alias).returned_quantum_values
            ),
            (expanded.qubits[0].id,),
        )

    def test_call_escape_lifetime_tracks_a_returned_callee_value_in_its_caller(self) -> None:
        expanded = expand_logical_module(_consume_prepared.to_logical_module())
        analysis = analyze_logical_lifetimes(expanded)
        escaped_value_id = expanded.call_expansion.records[0].returned_logical_qubit_id
        assert escaped_value_id is not None

        lifetime = next(
            item for item in analysis.lifetimes if item.logical_qubit_id == escaped_value_id
        )
        self.assertEqual(lifetime.first_instruction_index, 0)
        self.assertEqual(lifetime.last_instruction_index, 1)
        self.assertEqual(lifetime.end_reason, LogicalLifetimeEndReason.CALL_ESCAPE)

    def test_returned_parameter_keeps_the_original_caller_value(self) -> None:
        compilation = compile_logical_module(_return_parameter_root.to_logical_module())
        expanded = compilation.expanded_program
        assert expanded is not None

        root_qubit = next(
            qubit for qubit in expanded.qubits if qubit.origin.call_instance_id is None
        )
        self.assertEqual(compilation.readout.quantum_return_ids(), (root_qubit.id,))
        self.assertEqual(len(expanded.qubits), 1)
        self.assertEqual(
            tuple(
                value.logical_qubit_id
                for value in run(_return_parameter_root).returned_quantum_values
            ),
            (root_qubit.id,),
        )

    def test_returned_parameter_does_not_create_call_escape_state(self) -> None:
        expanded = expand_logical_module(_consume_returned_parameter.to_logical_module())
        analysis = analyze_logical_lifetimes(expanded)

        self.assertEqual(len(expanded.qubits), 1)
        lifetime = analysis.lifetimes[0]
        self.assertEqual(lifetime.end_reason, LogicalLifetimeEndReason.PROGRAM_END)

    def test_nested_call_instance_ids_include_the_complete_call_path(self) -> None:
        module = _nested_prepare.to_logical_module()
        expanded = expand_logical_module(module)
        compilation = compile_logical_module(module)
        outer, inner = expanded.call_expansion.records

        self.assertEqual(
            outer.call_instance_id,
            CallInstanceId(f"{module.entry_program_id}:call:{outer.call_operation_id}"),
        )
        self.assertEqual(
            inner.call_instance_id,
            CallInstanceId(f"{outer.call_instance_id}:call:{inner.call_operation_id}"),
        )
        invoked = next(
            instruction for instruction in expanded.instructions if len(instruction.call_stack) == 2
        )
        self.assertEqual(
            tuple(frame.call_operation_id for frame in invoked.call_stack),
            (outer.call_operation_id, inner.call_operation_id),
        )
        assert inner.returned_logical_qubit_id is not None
        self.assertEqual(
            compilation.readout.quantum_return_ids(),
            (inner.returned_logical_qubit_id,),
        )
        self.assertEqual(
            tuple(value.logical_qubit_id for value in run(_nested_prepare).returned_quantum_values),
            (inner.returned_logical_qubit_id,),
        )

    def test_lifetimes_retain_nonescaping_locals_without_reusing_slots(self) -> None:
        module = _scratch_root.to_logical_module()
        expanded = expand_logical_module(module)
        analysis = analyze_logical_lifetimes(expanded)
        compilation = compile_logical_module(module)

        record = expanded.call_expansion.records[0]
        temporary_id = record.instantiated_local_qubits[0]
        lifetime = next(
            item for item in analysis.lifetimes if item.logical_qubit_id == temporary_id
        )
        self.assertEqual(lifetime.end_reason, LogicalLifetimeEndReason.LAST_USE)
        self.assertGreaterEqual(lifetime.last_instruction_index, lifetime.first_instruction_index)
        self.assertLessEqual(analysis.peak_live_logical_values, len(expanded.qubits))
        self.assertEqual(
            compilation.logical_allocation.policy_name,
            EXPANDED_LOGICAL_ALLOCATION_POLICY_NAME,
        )
        self.assertEqual(
            compilation.logical_allocation.allocated_qubit_count,
            len(expanded.qubits),
        )
        self.assertEqual(
            tuple(entry.slot for entry in compilation.logical_allocation.entries),
            tuple(range(len(expanded.qubits))),
        )
        allocated = next(
            entry
            for entry in compilation.logical_allocation.entries
            if entry.logical_qubit_id == temporary_id
        )
        self.assertIsNotNone(allocated.origin)
        assert allocated.origin is not None
        self.assertEqual(allocated.origin.call_instance_id, record.call_instance_id)

    def test_unsupported_call_result_shapes_are_rejected(self) -> None:
        for function in (_assigns_bit_result, _assigns_tuple_result, _assigns_none_result):
            with self.subTest(function=function.__name__):
                with self.assertRaises(PythonFrontendError) as captured:
                    function.to_logical_module()
                self.assertEqual(captured.exception.diagnostics[0].code, "P116")
