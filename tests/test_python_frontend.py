from __future__ import annotations

import unittest

from ariadion import (
    Bit,
    Program,
    Qubit,
    UnboundQuantumParameterError,
    basis,
    cx,
    deg,
    h,
    quantum,
    rad,
    run,
    rx,
    ry,
    rz,
    turns,
    x,
    z,
)
from ariadion_core import LogicalQubitId, ProgramId
from ariadion_frontend_python import (
    ExplicitSourceProvider,
    PythonFrontendError,
    PythonFunctionSource,
    QuantumFunction,
    QuantumFunctionConfig,
    capture_python_function,
    explicit_quantum_function,
)
from ariadion_ir import OpCode
from ariadion_semantics import (
    LogicalGateOperation,
    LogicalProgram,
    LogicalQubitValue,
    LogicalRotationOperation,
    NoReturn,
    NoneReturn,
    QuantumParameter,
    ReturnValueKind,
    ReturnValueRef,
    ScalarReturn,
    TupleReturn,
)


@quantum(basis=basis.z)
def _bell() -> tuple[Bit, Bit]:
    left = Qubit()
    right = Qubit()
    h(left)
    cx(left, right)
    return left, right


@quantum
def _aliased_value() -> Qubit:
    value = Qubit()
    alias = value
    h(alias)
    return value


hadamard = h


@quantum
def _aliased_intrinsic() -> Qubit:
    value = Qubit()
    hadamard(value)
    return value


@quantum
def _x_and_z() -> Qubit:
    value = Qubit()
    x(value)
    z(value)
    return value


@quantum
def _scalar_bit() -> Bit:
    value = Qubit()
    h(value)
    return value


@quantum
def _scalar_qubit() -> Qubit:
    value = Qubit()
    h(value)
    return value


@quantum
def _one_tuple() -> tuple[Bit]:
    value = Qubit()
    return (value,)


@quantum
def _nested_mixed() -> tuple[Bit, tuple[Bit, Qubit]]:
    left = Qubit()
    right = Qubit()
    output = Qubit()
    h(left)
    cx(left, right)
    return left, (right, output)


@quantum
def _none_return() -> None:
    value = Qubit()
    h(value)


@quantum
def _rotation_degrees() -> Qubit:
    target = Qubit()
    rx(target, deg(190))
    return target


@quantum
def _rotation_radians() -> Qubit:
    target = Qubit()
    ry(target, rad(2))
    return target


@quantum
def _rotation_turns() -> Qubit:
    target = Qubit()
    rz(target, turns(0.25))
    return target


@quantum
def _rotation_parameter(target: Qubit) -> Qubit:
    rx(target, deg(190))
    return target


def _explicit_placeholder() -> None:
    return None


def _exploding_body() -> Qubit:
    raise AssertionError("The decorated quantum function body must not run.")


class PythonFrontendTests(unittest.TestCase):
    def test_public_bell_captures_and_executes_without_running_its_body(self) -> None:
        program = _bell.to_logical_program()
        result = run(_bell)

        self.assertEqual(tuple(value.display_name for value in program.qubits), ("left", "right"))
        self.assertEqual(len(program.instructions), 4)
        self.assertIsInstance(program.instructions[0], LogicalGateOperation)
        self.assertIsInstance(program.instructions[1], LogicalGateOperation)
        self.assertEqual(program.instructions[0].opcode.value, "h")
        self.assertEqual(program.instructions[1].opcode.value, "cx")
        self.assertEqual(
            tuple(reference.kind for reference in (program.return_shape.items[0].value,
                                                    program.return_shape.items[1].value)),
            (ReturnValueKind.CLASSICAL_BIT, ReturnValueKind.CLASSICAL_BIT),
        )
        assert result.classical_output_distribution is not None
        self._assert_probabilities(
            result.classical_output_distribution.probabilities,
            (0.5, 0.0, 0.0, 0.5),
        )
        with self.assertRaisesRegex(RuntimeError, "compiled rather than called"):
            _bell()

    def test_capture_and_exact_execution_never_call_the_python_body(self) -> None:
        source = self._source(
            "def _exploding_body() -> Qubit:\n"
            "    target = Qubit()\n"
            "    h(target)\n"
            "    return target\n",
            qualified_name="_exploding_body",
        )
        wrapper = explicit_quantum_function(_exploding_body, source)

        program = wrapper.to_logical_program()
        result = run(wrapper)
        captured = capture_python_function(
            _exploding_body,
            source_provider=ExplicitSourceProvider(source),
        )

        self.assertEqual(len(program.instructions), 1)
        self.assertEqual(captured.to_json(), program.to_json())
        self.assertEqual(len(result.returned_quantum_values), 1)

    def test_function_metadata_and_source_based_capture_are_preserved(self) -> None:
        self.assertEqual(_bell.__name__, "_bell")
        self.assertEqual(_bell.__qualname__, "_bell")
        self.assertEqual(_bell.__module__, __name__)
        self.assertEqual(_bell.__doc__, _bell.python_function.__doc__)
        self.assertTrue(callable(_bell.__wrapped__))
        self.assertIs(_bell.__wrapped__, _bell.python_function)

        first = _bell.to_logical_program()
        second = _bell.to_logical_program()

        self.assertEqual(first.to_json(), second.to_json())
        self.assertIs(first, second)
        self.assertEqual(first.id, ProgramId(f"python:{__name__}:_bell"))
        self.assertNotEqual(first.qubits[0].id, first.qubits[1].id)
        self.assertIn("python:qubit-declaration", first.qubits[0].id)

    def test_alias_assignment_preserves_one_logical_quantum_value(self) -> None:
        program = _aliased_value.to_logical_program()
        instruction = program.instructions[0]

        self.assertEqual(len(program.qubits), 1)
        self.assertIsInstance(instruction, LogicalGateOperation)
        self.assertEqual(instruction.targets, (program.qubits[0].id,))

    def test_intrinsic_import_alias_resolves_by_marker_identity(self) -> None:
        program = _aliased_intrinsic.to_logical_program()

        self.assertEqual(program.instructions[0].opcode.value, "h")

    def test_public_x_and_z_markers_lower_to_their_logical_opcodes(self) -> None:
        program = _x_and_z.to_logical_program()

        self.assertEqual(
            tuple(instruction.opcode.value for instruction in program.instructions),
            ("x", "z"),
        )

    def test_shadowed_intrinsic_is_rejected(self) -> None:
        namespace = {"Qubit": Qubit, "h": lambda value: value}
        exec(
            "def shadowed() -> Qubit:\n"
            "    value = Qubit()\n"
            "    h(value)\n"
            "    return value\n",
            namespace,
        )
        shadowed = namespace["shadowed"]
        source = self._source(
            "def shadowed() -> Qubit:\n"
            "    value = Qubit()\n"
            "    h(value)\n"
            "    return value\n",
            qualified_name="shadowed",
        )

        with self.assertRaises(PythonFrontendError) as captured:
            explicit_quantum_function(shadowed, source).to_logical_program()

        self.assertEqual(captured.exception.diagnostics[0].code, "P104")

    def test_invalid_intrinsic_calls_are_source_linked_p105_diagnostics(self) -> None:
        for source_text in (
            "def invalid() -> Qubit:\n"
            "    target = Qubit()\n"
            "    h()\n"
            "    return target\n",
            "def invalid() -> Qubit:\n"
            "    target = Qubit()\n"
            "    cx(target, target)\n"
            "    return target\n",
        ):
            with self.subTest(source_text=source_text):
                wrapper = self._explicit_wrapper(source_text, qualified_name="invalid")
                with self.assertRaises(PythonFrontendError) as captured:
                    wrapper.to_logical_program()
                self.assertEqual(captured.exception.diagnostics[0].code, "P105")

    def test_scalar_bit_return_infers_one_terminal_observation(self) -> None:
        program = _scalar_bit.to_logical_program()

        self.assertEqual(len(program.classical_bits), 1)
        self.assertEqual(program.instructions[-1].reason.value, "classical_return")
        self.assertEqual(program.return_shape.value.kind, ReturnValueKind.CLASSICAL_BIT)
        distribution = run(_scalar_bit).classical_output_distribution
        assert distribution is not None
        self._assert_probabilities(distribution.probabilities, (0.5, 0.5))

    def test_scalar_qubit_return_does_not_infer_an_observation(self) -> None:
        program = _scalar_qubit.to_logical_program()
        result = run(_scalar_qubit)

        self.assertEqual(program.classical_bits, ())
        self.assertIsInstance(program.return_shape, ScalarReturn)
        self.assertEqual(program.return_shape.value.kind, ReturnValueKind.QUANTUM_VALUE)
        self.assertIsNone(result.classical_output_distribution)
        self.assertEqual(len(result.returned_quantum_values), 1)

    def test_tuple_and_nested_mixed_returns_preserve_their_shape(self) -> None:
        one_tuple = _one_tuple.to_logical_program()
        nested = _nested_mixed.to_logical_program()

        self.assertIsInstance(one_tuple.return_shape, TupleReturn)
        self.assertEqual(len(one_tuple.return_shape.items), 1)
        self.assertIsInstance(nested.return_shape, TupleReturn)
        self.assertIsInstance(nested.return_shape.items[1], TupleReturn)
        self.assertEqual(len(nested.classical_bits), 2)
        self.assertEqual(
            tuple(value.display_name for value in run(_nested_mixed).returned_quantum_values),
            ("output",),
        )

    def test_none_return_is_whole_function_only(self) -> None:
        program = _none_return.to_logical_program()

        self.assertIsInstance(program.return_shape, NoneReturn)
        self.assertIs(NoReturn, NoneReturn)
        self.assertIsInstance(NoReturn(), NoneReturn)
        self.assertEqual(run(_none_return).returned_quantum_values, ())
        with self.assertRaisesRegex(ValueError, "scalar or tuple return"):
            TupleReturn((NoneReturn(),))

    def test_rotations_capture_explicit_angle_units_without_executing_angle_helpers(self) -> None:
        cases = (
            (_rotation_degrees, OpCode.RX, "degrees", 190.0),
            (_rotation_radians, OpCode.RY, "radians", 2.0),
            (_rotation_turns, OpCode.RZ, "turns", 0.25),
        )

        for function, opcode, unit, source_value in cases:
            with self.subTest(unit=unit):
                program = function.to_logical_program()
                instruction = program.instructions[0]
                result = run(function)

                self.assertIsInstance(instruction, LogicalRotationOperation)
                self.assertEqual(instruction.angle.source_unit.value, unit)
                self.assertEqual(instruction.angle.source_value, source_value)
                self.assertEqual(result.compilation.ir.operations[0].opcode, opcode)

    def test_bare_or_computed_rotation_angles_are_rejected(self) -> None:
        for source_text in (
            "def invalid() -> Qubit:\n"
            "    target = Qubit()\n"
            "    rx(target, 90)\n"
            "    return target\n",
            "def invalid() -> Qubit:\n"
            "    target = Qubit()\n"
            "    rx(target, deg(40 + 50))\n"
            "    return target\n",
            "def invalid() -> Qubit:\n"
            "    target = Qubit()\n"
            "    rz(target, turns(1e308))\n"
            "    return target\n",
        ):
            with self.subTest(source_text=source_text):
                wrapper = self._explicit_wrapper(source_text, qualified_name="invalid")
                with self.assertRaises(PythonFrontendError) as captured:
                    wrapper.to_logical_program()
                self.assertEqual(captured.exception.diagnostics[0].code, "P112")

    def test_return_shape_mismatch_is_source_linked(self) -> None:
        wrapper = self._explicit_wrapper(
            "def mismatch() -> tuple[Bit, Bit]:\n"
            "    target = Qubit()\n"
            "    return target\n",
            qualified_name="mismatch",
            starting_line=40,
        )

        with self.assertRaises(PythonFrontendError) as captured:
            wrapper.to_logical_program()

        diagnostic = captured.exception.diagnostics[0]
        self.assertEqual(diagnostic.code, "P110")
        self.assertIsNotNone(diagnostic.source_range)
        assert diagnostic.source_range is not None
        self.assertEqual(diagnostic.source_range.line, 42)
        self.assertEqual(diagnostic.program_id, ProgramId("python:tests.frontend:mismatch"))

    def test_custom_annotation_aliases_are_rejected_without_evaluation(self) -> None:
        namespace = {"Qubit": Qubit, "B": Bit}
        exec(
            "def aliased_annotation() -> B:\n"
            "    target = Qubit()\n"
            "    return target\n",
            namespace,
        )
        source = self._source(
            "def aliased_annotation() -> B:\n"
            "    target = Qubit()\n"
            "    return target\n",
            qualified_name="aliased_annotation",
        )

        with self.assertRaises(PythonFrontendError) as captured:
            explicit_quantum_function(namespace["aliased_annotation"], source).to_logical_program()

        self.assertEqual(captured.exception.diagnostics[0].code, "P109")

    def test_same_value_cannot_have_both_classical_and_quantum_return_leaves(self) -> None:
        wrapper = self._explicit_wrapper(
            "def mixed() -> tuple[Bit, Qubit]:\n"
            "    target = Qubit()\n"
            "    return target, target\n",
            qualified_name="mixed",
        )

        with self.assertRaises(PythonFrontendError) as captured:
            wrapper.to_logical_program()

        self.assertEqual(captured.exception.diagnostics[0].code, "P110")

    def test_postponed_annotations_are_parsed_from_source_not_runtime_hints(self) -> None:
        wrapper = self._explicit_wrapper(
            "from __future__ import annotations\n"
            "\n"
            "def postponed() -> Qubit:\n"
            "    target = Qubit()\n"
            "    return target\n",
            qualified_name="postponed",
        )

        self.assertIsInstance(wrapper.to_logical_program().return_shape, ScalarReturn)

    def test_unsupported_control_flow_is_rejected(self) -> None:
        wrapper = self._explicit_wrapper(
            "def branch() -> Qubit:\n"
            "    target = Qubit()\n"
            "    if True:\n"
            "        h(target)\n"
            "    return target\n",
            qualified_name="branch",
        )

        with self.assertRaises(PythonFrontendError) as captured:
            wrapper.to_logical_program()

        self.assertEqual(captured.exception.diagnostics[0].code, "P102")

    def test_explicit_source_provider_maps_ranges_to_original_lines(self) -> None:
        wrapper = self._explicit_wrapper(
            "def ranged() -> Qubit:\n"
            "    target = Qubit()\n"
            "    h(target)\n"
            "    return target\n",
            qualified_name="ranged",
            starting_line=80,
            file="untitled:frontend-test.py",
        )
        program = wrapper.to_logical_program()
        instruction = program.instructions[0]

        self.assertIsNotNone(instruction.source)
        assert instruction.source is not None
        self.assertEqual(instruction.source.line, 82)
        self.assertEqual(instruction.source.file, "untitled:frontend-test.py")
        self.assertGreaterEqual(instruction.source.column or 0, 1)

    def test_unavailable_inspected_source_produces_p100(self) -> None:
        dynamic = eval("lambda: None")
        wrapper = QuantumFunction(dynamic, QuantumFunctionConfig())

        with self.assertRaises(PythonFrontendError) as captured:
            wrapper.to_logical_program()

        self.assertEqual(captured.exception.diagnostics[0].code, "P100")

    def test_parser_and_source_provider_failures_are_structured(self) -> None:
        malformed = self._explicit_wrapper(
            "def malformed() -> Qubit\n"
            "    target = Qubit()\n",
            qualified_name="malformed",
        )

        with self.assertRaises(PythonFrontendError) as parser_error:
            malformed.to_logical_program()

        self.assertEqual(parser_error.exception.diagnostics[0].code, "P101")

        class FailingSourceProvider:
            def source_for(self, function: object) -> PythonFunctionSource:
                del function
                raise AssertionError("source provider failure")

        wrapper = QuantumFunction(
            _explicit_placeholder,
            QuantumFunctionConfig(),
            FailingSourceProvider(),
        )
        with self.assertRaises(PythonFrontendError) as provider_error:
            wrapper.to_logical_program()

        self.assertEqual(provider_error.exception.diagnostics[0].code, "P100")

    def test_quantum_parameters_capture_but_standalone_execution_rejects_them(self) -> None:
        program = _rotation_parameter.to_logical_program()

        self.assertEqual(len(program.parameters), 1)
        parameter = program.parameters[0]
        self.assertEqual(parameter.name, "target")
        self.assertEqual(parameter.position, 0)
        self.assertEqual(parameter.logical_qubit_id, program.qubits[0].id)
        self.assertIsInstance(parameter, QuantumParameter)
        self.assertEqual(program.to_dict()["parameters"][0]["name"], "target")
        with self.assertRaises(UnboundQuantumParameterError) as captured:
            run(_rotation_parameter)
        self.assertEqual(captured.exception.code, "P113")
        self.assertIn("target", str(captured.exception))

    def test_semantic_parameter_validation_preserves_hand_built_programs(self) -> None:
        parameter = QuantumParameter("input", 0, LogicalQubitId("logical:input"))
        program = self._manual_parameter_program(parameter)

        self.assertEqual(program.parameters, (parameter,))
        with self.assertRaisesRegex(ValueError, "contiguous from zero"):
            self._manual_parameter_program(
                QuantumParameter("input", 1, LogicalQubitId("logical:input"))
            )
        with self.assertRaisesRegex(ValueError, "declared logical qubit"):
            self._manual_parameter_program(
                QuantumParameter("input", 0, LogicalQubitId("logical:missing"))
            )
        self.assertIsNotNone(run(Program(1).h(0)))

    def test_explicit_capture_is_reproducible_without_function_object_identity(self) -> None:
        source_text = (
            "def reproducible() -> Qubit:\n"
            "    target = Qubit()\n"
            "    h(target)\n"
            "    return target\n"
        )
        first = self._explicit_wrapper(source_text, qualified_name="reproducible")
        second = self._explicit_wrapper(source_text, qualified_name="reproducible")

        self.assertEqual(
            first.to_logical_program().to_json(),
            second.to_logical_program().to_json(),
        )

    def test_source_origin_is_part_of_the_capture_fingerprint(self) -> None:
        text = (
            "def origin() -> Qubit:\n"
            "    target = Qubit()\n"
            "    return target\n"
        )

        class SwitchingSourceProvider:
            def __init__(self, source: PythonFunctionSource) -> None:
                self.source = source

            def source_for(self, function: object) -> PythonFunctionSource:
                del function
                return self.source

        provider = SwitchingSourceProvider(
            self._source(text, qualified_name="origin", starting_line=1)
        )
        wrapper = QuantumFunction(_explicit_placeholder, QuantumFunctionConfig(), provider)
        first = wrapper.to_logical_program()
        provider.source = self._source(text, qualified_name="origin", starting_line=50)
        second = wrapper.to_logical_program()

        self.assertIsNot(first, second)
        assert first.qubits[0].source is not None
        assert second.qubits[0].source is not None
        self.assertEqual(first.qubits[0].source.line, 2)
        self.assertEqual(second.qubits[0].source.line, 51)

    def test_marker_calls_outside_frontend_raise_clear_errors(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "intrinsic `h` cannot execute"):
            h(Qubit())

    @staticmethod
    def _source(
        text: str,
        *,
        qualified_name: str,
        starting_line: int = 1,
        file: str | None = "tests/frontend_source.py",
    ) -> PythonFunctionSource:
        return PythonFunctionSource(
            text=text,
            file=file,
            starting_line=starting_line,
            module_name="tests.frontend",
            qualified_name=qualified_name,
        )

    def _explicit_wrapper(
        self,
        text: str,
        *,
        qualified_name: str,
        starting_line: int = 1,
        file: str | None = "tests/frontend_source.py",
    ) -> QuantumFunction:
        source = self._source(
            text,
            qualified_name=qualified_name,
            starting_line=starting_line,
            file=file,
        )
        return explicit_quantum_function(
            _explicit_placeholder,
            source,
            config=QuantumFunctionConfig(),
        )

    @staticmethod
    def _manual_parameter_program(parameter: QuantumParameter):
        value = LogicalQubitValue(LogicalQubitId("logical:input"), "input")
        return LogicalProgram(
            id=ProgramId("logical:parameter"),
            name="parameter",
            qubits=(value,),
            instructions=(),
            return_shape=ScalarReturn(
                ReturnValueRef(
                    ReturnValueKind.QUANTUM_VALUE,
                    value.id,
                )
            ),
            parameters=(parameter,),
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
