from __future__ import annotations

import unittest

from ariadion import Bit, Qubit, TraceCaptureOptions, cx, h, quantum, run, x, z
from ariadion_cli.trace_view import render_trace_step
from ariadion_core import LogicalOperationId, LogicalQubitId, ProgramId
from ariadion_frontend_python import (
    PythonFrontendError,
    PythonFunctionSource,
    explicit_quantum_function,
)
from ariadion_ir import OpCode
from ariadion_runtime import TraceDebuggerSession, inspect_execution_trace
from ariadion_semantics import (
    LogicalCallOperation,
    LogicalModule,
    LogicalProgram,
    LogicalQubitValue,
    NoneReturn,
    QuantumArgumentBinding,
    QuantumParameter,
)
from daidalon import CompileError, compile_logical_module


@quantum
def _entangle(left: Qubit, right: Qubit) -> None:
    h(left)
    cx(left, right)


@quantum
def _composed_bell() -> tuple[Bit, Bit]:
    left = Qubit()
    right = Qubit()
    _entangle(left, right)
    return left, right


_entangle_alias = _entangle


@quantum
def _alias_composed_bell() -> tuple[Bit, Bit]:
    left = Qubit()
    right = Qubit()
    _entangle_alias(left, right)
    return left, right


@quantum
def _mark_first(first: Qubit, _second: Qubit) -> None:
    x(first)
    z(_second)


@quantum
def _bound_in_order() -> tuple[Bit, Bit]:
    first = Qubit()
    second = Qubit()
    _mark_first(first, second)
    return first, second


@quantum
def _bound_reversed() -> tuple[Bit, Bit]:
    first = Qubit()
    second = Qubit()
    _mark_first(second, first)
    return first, second


@quantum
def _controlled_x(control: Qubit, target: Qubit) -> None:
    cx(control, target)


@quantum
def _calls_aliased_controlled_x() -> None:
    value = Qubit()
    _controlled_x(value, value)


@quantum
def _wrong_call_arity() -> Qubit:
    value = Qubit()
    _entangle(value)
    return value


@quantum
def _returns_qubit(value: Qubit) -> Qubit:
    return value


@quantum
def _returns_bit(value: Qubit) -> Bit:
    return value


@quantum
def _local_callee(_value: Qubit) -> None:
    temporary = Qubit()
    h(temporary)
    z(_value)


@quantum
def _calls_returning_qubit() -> None:
    value = Qubit()
    _returns_qubit(value)


@quantum
def _calls_returning_bit() -> None:
    value = Qubit()
    _returns_bit(value)


@quantum
def _calls_local_callee() -> None:
    value = Qubit()
    _local_callee(value)


@quantum
def _direct_recursive(value: Qubit) -> None:
    _direct_recursive(value)


@quantum
def _mutual_a(value: Qubit) -> None:
    _mutual_b(value)


@quantum
def _mutual_b(value: Qubit) -> None:
    _mutual_a(value)


@quantum
def _twice_composed_bell() -> tuple[Bit, Bit, Bit, Bit]:
    first_left = Qubit()
    first_right = Qubit()
    second_left = Qubit()
    second_right = Qubit()
    _entangle(first_left, first_right)
    _entangle(second_left, second_right)
    return first_left, first_right, second_left, second_right


@quantum
def _nested_entangle(left: Qubit, right: Qubit) -> None:
    _entangle(left, right)


@quantum
def _nested_composed_bell() -> tuple[Bit, Bit]:
    left = Qubit()
    right = Qubit()
    _nested_entangle(left, right)
    return left, right


@quantum(program_id=ProgramId("tests:colliding-callee"))
def _first_colliding_callee(value: Qubit) -> None:
    x(value)


@quantum(program_id=ProgramId("tests:colliding-callee"))
def _second_colliding_callee(value: Qubit) -> None:
    z(value)


@quantum
def _calls_colliding_callees() -> None:
    value = Qubit()
    _first_colliding_callee(value)
    _second_colliding_callee(value)


def _ordinary_python_function(value: object) -> None:
    del value


@quantum
def _calls_ordinary_python_function() -> None:
    value = Qubit()
    _ordinary_python_function(value)


@quantum
def _root_parameter(value: Qubit) -> None:
    h(value)


class QuantumCompositionTests(unittest.TestCase):
    def test_composed_bell_executes_and_callee_body_never_executes(self) -> None:
        result = run(_composed_bell)

        self.assertIsNotNone(result.classical_output_distribution)
        assert result.classical_output_distribution is not None
        self._assert_probabilities(
            result.classical_output_distribution.probabilities,
            (0.5, 0.0, 0.0, 0.5),
        )
        with self.assertRaisesRegex(RuntimeError, "compiled rather than called"):
            _entangle(Qubit(), Qubit())

    def test_individual_program_retains_a_semantic_call(self) -> None:
        program = _composed_bell.to_logical_program()

        calls = tuple(
            instruction
            for instruction in program.instructions
            if isinstance(instruction, LogicalCallOperation)
        )
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].callee_program_id, _entangle.to_logical_program().id)
        self.assertEqual(
            tuple(binding.argument_id for binding in calls[0].arguments),
            tuple(qubit.id for qubit in program.qubits),
        )

    def test_caller_values_bind_to_callee_parameters_in_declared_order(self) -> None:
        result = run(_bound_in_order)

        assert result.classical_output_distribution is not None
        self._assert_probabilities(
            result.classical_output_distribution.probabilities,
            (0.0, 1.0, 0.0, 0.0),
        )

    def test_reversed_callee_arguments_change_binding_deterministically(self) -> None:
        first = run(_bound_reversed)
        second = run(_bound_reversed)

        assert first.classical_output_distribution is not None
        self._assert_probabilities(
            first.classical_output_distribution.probabilities,
            (0.0, 0.0, 1.0, 0.0),
        )
        self.assertEqual(first.compilation.to_json(), second.compilation.to_json())

    def test_aliased_call_arguments_cannot_lower_an_invalid_controlled_gate(self) -> None:
        with self.assertRaises(CompileError) as captured:
            compile_logical_module(_calls_aliased_controlled_x.to_logical_module())

        diagnostic = captured.exception.diagnostics[0]
        self.assertEqual(diagnostic.code, "A205")
        self.assertIsNotNone(diagnostic.source)

    def test_quantum_function_alias_resolves_by_object_identity(self) -> None:
        result = run(_alias_composed_bell)

        assert result.classical_output_distribution is not None
        self._assert_probabilities(
            result.classical_output_distribution.probabilities,
            (0.5, 0.0, 0.0, 0.5),
        )

    def test_non_ariadion_call_is_rejected(self) -> None:
        with self.assertRaises(PythonFrontendError) as captured:
            _calls_ordinary_python_function.to_logical_module()

        self.assertEqual(captured.exception.diagnostics[0].code, "P103")

    def test_wrong_call_arity_is_source_linked(self) -> None:
        with self.assertRaises(PythonFrontendError) as captured:
            _wrong_call_arity.to_logical_module()

        diagnostic = captured.exception.diagnostics[0]
        self.assertEqual(diagnostic.code, "P105")
        self.assertIsNotNone(diagnostic.source_range)
        self.assertEqual(
            diagnostic.program_id,
            ProgramId(f"python:{__name__}:_wrong_call_arity"),
        )

    def test_quantum_returning_callee_is_rejected(self) -> None:
        self._assert_unsupported_callee(_calls_returning_qubit, "return None")

    def test_classical_returning_callee_is_rejected(self) -> None:
        self._assert_unsupported_callee(_calls_returning_bit)

    def test_observing_callee_is_rejected(self) -> None:
        self._assert_unsupported_callee(_calls_returning_bit, "observations")

    def test_local_qubit_callee_is_rejected(self) -> None:
        self._assert_unsupported_callee(_calls_local_callee, "local Qubit")

    def test_direct_recursion_is_source_linked(self) -> None:
        with self.assertRaises(PythonFrontendError) as captured:
            _direct_recursive.to_logical_module()

        diagnostic = captured.exception.diagnostics[0]
        self.assertEqual(diagnostic.code, "P115")
        self.assertIsNotNone(diagnostic.source_range)

    def test_mutual_recursion_is_source_linked(self) -> None:
        with self.assertRaises(PythonFrontendError) as captured:
            _mutual_a.to_logical_module()

        diagnostic = captured.exception.diagnostics[0]
        self.assertEqual(diagnostic.code, "P115")
        self.assertIsNotNone(diagnostic.source_range)

    def test_distinct_callees_cannot_share_a_program_id(self) -> None:
        with self.assertRaises(PythonFrontendError) as captured:
            _calls_colliding_callees.to_logical_module()

        diagnostic = captured.exception.diagnostics[0]
        self.assertEqual(diagnostic.code, "P117")
        self.assertIsNotNone(diagnostic.source_range)

    def test_repeated_callee_invocations_have_distinct_ir_ids(self) -> None:
        module = _twice_composed_bell.to_logical_module()
        compilation = compile_logical_module(module)
        invoked_h_operations = tuple(
            operation
            for operation in compilation.ir.operations
            if operation.opcode is OpCode.H and operation.provenance is not None
        )

        self.assertEqual(len(invoked_h_operations), 2)
        self.assertNotEqual(invoked_h_operations[0].id, invoked_h_operations[1].id)
        self.assertEqual(
            tuple(len(operation.provenance.call_stack) for operation in invoked_h_operations),
            (1, 1),
        )

    def test_nested_calls_expand_with_an_ordered_call_stack(self) -> None:
        module = _nested_composed_bell.to_logical_module()
        first_compilation = compile_logical_module(module)
        second_compilation = compile_logical_module(module)
        result = run(_nested_composed_bell)
        invoked_h_operation = next(
            operation
            for operation in first_compilation.ir.operations
            if operation.opcode is OpCode.H
        )

        assert result.classical_output_distribution is not None
        self._assert_probabilities(
            result.classical_output_distribution.probabilities,
            (0.5, 0.0, 0.0, 0.5),
        )
        self.assertEqual(first_compilation.to_json(), second_compilation.to_json())
        assert invoked_h_operation.provenance is not None
        self.assertEqual(len(invoked_h_operation.provenance.call_stack), 2)
        outer_frame, inner_frame = invoked_h_operation.provenance.call_stack
        self.assertEqual(
            outer_frame.caller_program_id,
            _nested_composed_bell.to_logical_program().id,
        )
        self.assertEqual(
            outer_frame.callee_program_id,
            _nested_entangle.to_logical_program().id,
        )
        self.assertEqual(
            inner_frame.caller_program_id,
            _nested_entangle.to_logical_program().id,
        )
        self.assertEqual(
            inner_frame.callee_program_id,
            _entangle.to_logical_program().id,
        )

    def test_module_compilation_is_byte_stable(self) -> None:
        module = _composed_bell.to_logical_module()

        self.assertEqual(
            compile_logical_module(module).to_json(),
            compile_logical_module(module).to_json(),
        )
        self.assertEqual(module.to_json(), _composed_bell.to_logical_module().to_json())

    def test_lowered_operation_keeps_definition_and_invocation_provenance(self) -> None:
        module = _composed_bell.to_logical_module()
        operation = compile_logical_module(module).ir.operations[0]
        entangle_program = _entangle.to_logical_program()
        caller_program = _composed_bell.to_logical_program()

        self.assertEqual(operation.opcode, OpCode.H)
        self.assertEqual(
            operation.source.program_id if operation.source is not None else None,
            entangle_program.id,
        )
        assert operation.provenance is not None
        self.assertEqual(
            operation.provenance.parent_logical_operation_ids,
            (entangle_program.instructions[0].id,),
        )
        self.assertEqual(len(operation.provenance.call_stack), 1)
        frame = operation.provenance.call_stack[0]
        self.assertEqual(frame.caller_program_id, caller_program.id)
        self.assertEqual(frame.callee_program_id, entangle_program.id)
        self.assertIsNotNone(frame.call_source)
        self.assertEqual(
            frame.call_source.program_id if frame.call_source is not None else None,
            caller_program.id,
        )

    def test_debugger_exposes_definition_and_call_locations(self) -> None:
        result = run(_composed_bell, trace=TraceCaptureOptions(enabled=True))
        assert result.trace is not None
        session = TraceDebuggerSession(
            result.compilation.ir,
            result.trace,
            inspect_execution_trace(result.trace),
        )
        view = session.current_view
        rendered = render_trace_step(view)

        self.assertIsNotNone(view.source)
        self.assertEqual(len(view.call_stack), 1)
        self.assertEqual(len(session.inspection.steps[0].call_stack), 1)
        self.assertEqual(len(view.to_dict()["call_stack"]), 1)
        self.assertIn("Defined at:", rendered)
        self.assertIn("Called from:", rendered)

    def test_root_unbound_parameters_are_not_composition_bindings(self) -> None:
        with self.assertRaisesRegex(ValueError, "P113"):
            run(_root_parameter)

    def test_annotation_names_must_resolve_to_ariadion_bindings(self) -> None:
        parameter = self._explicit_function(
            "def wrong_parameter(value: Qubit) -> None:\n"
            "    h(value)\n",
            "wrong_parameter",
            {"Qubit": object(), "h": h},
        )
        return_value = self._explicit_function(
            "def wrong_return() -> Bit:\n"
            "    value = Qubit()\n"
            "    return value\n",
            "wrong_return",
            {"Qubit": Qubit, "Bit": object()},
        )
        tuple_value = self._explicit_function(
            "def wrong_tuple() -> tuple[Qubit]:\n"
            "    value = Qubit()\n"
            "    return (value,)\n",
            "wrong_tuple",
            {"Qubit": Qubit, "tuple": object()},
        )

        for wrapper, code in ((parameter, "P108"), (return_value, "P109"), (tuple_value, "P109")):
            with self.subTest(code=code):
                with self.assertRaises(PythonFrontendError) as captured:
                    wrapper.to_logical_program()
                self.assertEqual(captured.exception.diagnostics[0].code, code)

    def test_rebound_intrinsic_alias_cannot_return_stale_semantics(self) -> None:
        namespace: dict[str, object] = {"Qubit": Qubit, "marker": h}
        source_text = (
            "def rebound() -> Qubit:\n"
            "    value = Qubit()\n"
            "    marker(value)\n"
            "    return value\n"
        )
        namespace["__name__"] = "tests.rebound"
        exec(source_text, namespace)
        function = namespace["rebound"]
        assert callable(function)
        wrapper = explicit_quantum_function(
            function,
            PythonFunctionSource(
                text=source_text,
                file="tests/rebound.py",
                starting_line=1,
                module_name="tests.rebound",
                qualified_name="rebound",
            ),
        )

        first = wrapper.to_logical_program()
        namespace["marker"] = x
        second = wrapper.to_logical_program()

        self.assertEqual(first.instructions[0].opcode.value, OpCode.H.value.lower())
        self.assertEqual(second.instructions[0].opcode.value, OpCode.X.value.lower())
        self.assertIsNot(first, second)

    def test_closure_backed_function_is_rejected_without_reading_cells(self) -> None:
        def outer():
            gate = h

            @quantum
            def inner(value: Qubit) -> None:
                gate(value)

            return inner

        wrapper = outer()
        with self.assertRaises(PythonFrontendError) as captured:
            wrapper.to_logical_program()

        self.assertEqual(captured.exception.diagnostics[0].code, "P114")

    def test_logical_module_validates_bindings_and_serializes_programs_stably(self) -> None:
        callee_id = ProgramId("logical:callee")
        parameter_id = LogicalQubitId("logical:callee:parameter")
        callee = LogicalProgram(
            id=callee_id,
            name="callee",
            qubits=(LogicalQubitValue(id=parameter_id),),
            instructions=(),
            return_shape=NoneReturn(),
            parameters=(
                QuantumParameter(
                    name="value",
                    position=0,
                    logical_qubit_id=parameter_id,
                ),
            ),
        )
        caller_id = ProgramId("logical:caller")
        argument_id = LogicalQubitId("logical:caller:argument")
        call = LogicalCallOperation(
            id=LogicalOperationId("logical:caller:call"),
            callee_program_id=callee_id,
            arguments=(
                QuantumArgumentBinding(
                    parameter_id=parameter_id,
                    argument_id=argument_id,
                ),
            ),
        )
        caller = LogicalProgram(
            id=caller_id,
            name="caller",
            qubits=(LogicalQubitValue(id=argument_id),),
            instructions=(call,),
        )
        module = LogicalModule(
            entry_program_id=caller_id,
            programs=(callee, caller),
        )

        self.assertEqual(module.entry_program, caller)
        self.assertEqual(
            [program["id"] for program in module.to_dict()["programs"]],
            ["logical:callee", "logical:caller"],
        )

    def _assert_unsupported_callee(self, function: object, message: str | None = None) -> None:
        assert hasattr(function, "to_logical_module")
        with self.assertRaises(PythonFrontendError) as captured:
            function.to_logical_module()
        diagnostic = captured.exception.diagnostics[0]
        self.assertEqual(diagnostic.code, "P116")
        if message is not None:
            self.assertIn(message, diagnostic.message)
        self.assertIsNotNone(diagnostic.source_range)

    @staticmethod
    def _explicit_function(
        text: str,
        name: str,
        namespace: dict[str, object],
    ):
        namespace["__name__"] = "tests.annotation_binding"
        exec(text, namespace)
        function = namespace[name]
        assert callable(function)
        return explicit_quantum_function(
            function,
            PythonFunctionSource(
                text=text,
                file="tests/annotation_binding.py",
                starting_line=1,
                module_name="tests.annotation_binding",
                qualified_name=name,
            ),
        )

    def _assert_probabilities(
        self,
        actual: tuple[float, ...],
        expected: tuple[float, ...],
    ) -> None:
        self.assertEqual(len(actual), len(expected))
        for actual_value, expected_value in zip(actual, expected, strict=True):
            self.assertAlmostEqual(actual_value, expected_value, places=12)


if __name__ == "__main__":
    unittest.main()
