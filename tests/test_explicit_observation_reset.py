from __future__ import annotations

import unittest

from ariadion import (
    Bit,
    Qubit,
    SampledExecutionRequest,
    basis,
    cx,
    h,
    observe,
    quantum,
    reset,
    run,
    x,
)
from ariadion_frontend_python import PythonFrontendError
from ariadion_ir import OpCode
from ariadion_semantics import (
    LogicalResetOperation,
    Observation,
    ObservationReason,
    ReturnValueKind,
)
from ariadion_simulator import ExactResetUnsupportedError, ExactTerminalObservationError
from daidalon import CompileError, compile_logical_module, compile_logical_program


@quantum
def _explicit_observation() -> Bit:
    target = Qubit()
    h(target)
    result = observe(target)
    return result


@quantum
def _aliased_observation_result() -> Bit:
    target = Qubit()
    result = observe(target)
    alias = result
    return alias


@quantum
def _discarded_observation() -> None:
    target = Qubit()
    observe(target)


@quantum
def _mid_circuit_observation() -> Bit:
    target = Qubit()
    h(target)
    result = observe(target)
    x(target)
    return result


@quantum
def _source_reset() -> Bit:
    target = Qubit()
    x(target)
    reset(target)
    return target


@quantum
def _reset_helper(target: Qubit) -> None:
    reset(target)


@quantum
def _composed_source_reset() -> Bit:
    target = Qubit()
    x(target)
    _reset_helper(target)
    return target


@quantum
def _observation_helper(target: Qubit) -> None:
    observe(target)


@quantum
def _calls_observation_helper() -> None:
    target = Qubit()
    _observation_helper(target)


@quantum
def _inferred_terminal_observation() -> Bit:
    target = Qubit()
    h(target)
    return target


@quantum
def _bell() -> tuple[Bit, Bit]:
    left = Qubit()
    right = Qubit()
    h(left)
    cx(left, right)
    return left, right


@quantum(basis=basis.x)
def _x_basis_explicit_observation() -> Bit:
    target = Qubit()
    result = observe(target)
    return result


@quantum
def _observation_branch() -> Bit:
    target = Qubit()
    result = observe(target)
    if result:
        x(target)
    return result


@quantum
def _observation_as_gate_argument() -> Bit:
    target = Qubit()
    result = observe(target)
    h(result)
    return result


class ExplicitObservationAndResetTests(unittest.TestCase):
    def test_markers_cannot_execute_as_ordinary_python(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "intrinsic `observe` cannot execute"):
            observe(Qubit())
        with self.assertRaisesRegex(RuntimeError, "intrinsic `reset` cannot execute"):
            reset(Qubit())

    def test_explicit_observation_creates_one_classical_binding_and_return(self) -> None:
        program = _explicit_observation.to_logical_program()
        execution = run(_explicit_observation)
        observations = tuple(
            instruction
            for instruction in program.instructions
            if isinstance(instruction, Observation)
        )

        self.assertEqual(len(program.classical_bits), 1)
        self.assertEqual(len(observations), 1)
        observation = observations[0]
        self.assertEqual(observation.reason, ObservationReason.EXPLICIT)
        self.assertEqual(observation.basis, basis.z)
        self.assertEqual(program.classical_bits[0].display_name, "result")
        self.assertEqual(program.return_shape.value.kind, ReturnValueKind.CLASSICAL_BIT)
        self.assertEqual(program.return_shape.value.value_id, observation.result_id)
        self.assertEqual(len(program.instructions), 2)
        self.assertIsNotNone(execution.classical_output_distribution)
        assert execution.classical_output_distribution is not None
        self._assert_probabilities(
            execution.classical_output_distribution.probabilities,
            (0.5, 0.5),
        )

    def test_observation_result_alias_preserves_the_original_result_identity(self) -> None:
        program = _aliased_observation_result.to_logical_program()
        observations = tuple(
            instruction
            for instruction in program.instructions
            if isinstance(instruction, Observation)
        )

        self.assertEqual(len(program.classical_bits), 1)
        self.assertEqual(len(observations), 1)
        self.assertEqual(program.return_shape.value.value_id, observations[0].result_id)

    def test_discarded_explicit_observation_is_captured_without_a_return(self) -> None:
        program = _discarded_observation.to_logical_program()
        result = run(_discarded_observation)

        self.assertEqual(len(program.classical_bits), 1)
        self.assertEqual(len(program.instructions), 1)
        observation = program.instructions[0]
        self.assertIsInstance(observation, Observation)
        self.assertEqual(observation.reason, ObservationReason.EXPLICIT)
        self.assertEqual(result.returned_quantum_values, ())
        self.assertIsNone(result.classical_output_distribution)
        self.assertEqual(len(result.compilation.readout.observations), 1)

    def test_explicit_observation_uses_the_function_default_basis(self) -> None:
        program = _x_basis_explicit_observation.to_logical_program()
        observation = program.instructions[0]

        self.assertIsInstance(observation, Observation)
        self.assertEqual(observation.basis, basis.x)
        with self.assertRaises(CompileError) as captured:
            compile_logical_program(program)
        self.assertEqual(captured.exception.diagnostics[0].code, "A201")

    def test_source_reset_captures_and_lowers_without_replacing_the_value(self) -> None:
        program = _source_reset.to_logical_program()
        reset_instruction = next(
            instruction
            for instruction in program.instructions
            if isinstance(instruction, LogicalResetOperation)
        )
        compilation = compile_logical_program(program)

        self.assertEqual(reset_instruction.qubit_id, program.qubits[0].id)
        self.assertEqual(
            tuple(operation.opcode for operation in compilation.ir.operations),
            (OpCode.X, OpCode.RESET, OpCode.MEASURE),
        )
        self.assertEqual(compilation.ir.operations[1].targets, (0,))
        self.assertEqual(
            compilation.ir.operations[1].provenance.parent_logical_operation_ids,
            (reset_instruction.id,),
        )

    def test_sampled_source_observation_can_precede_a_gate(self) -> None:
        result = run(
            _mid_circuit_observation,
            execution=SampledExecutionRequest(shots=100, seed=21),
        )

        self.assertIsNotNone(result.classical_output)
        assert result.classical_output is not None
        self.assertEqual(sum(result.classical_output.counts), 100)
        self.assertEqual(
            tuple(operation.opcode for operation in result.compilation.ir.operations),
            (OpCode.H, OpCode.MEASURE, OpCode.X),
        )

    def test_exact_source_observation_before_a_gate_raises_a202(self) -> None:
        with self.assertRaises(ExactTerminalObservationError) as captured:
            run(_mid_circuit_observation)

        self.assertEqual(captured.exception.code, "A202")

    def test_sampled_source_reset_returns_zero(self) -> None:
        result = run(
            _source_reset,
            execution=SampledExecutionRequest(shots=100, seed=7),
        )

        self.assertIsNotNone(result.classical_output)
        assert result.classical_output is not None
        self.assertEqual(result.classical_output.counts, (100, 0))

    def test_exact_source_reset_raises_a203(self) -> None:
        with self.assertRaises(ExactResetUnsupportedError) as captured:
            run(_source_reset)

        self.assertEqual(captured.exception.code, "A203")

    def test_reset_is_supported_inside_a_none_returning_composed_helper(self) -> None:
        compilation = compile_logical_module(_composed_source_reset.to_logical_module())
        result = run(
            _composed_source_reset,
            execution=SampledExecutionRequest(shots=50, seed=3),
        )
        reset_operation = next(
            operation
            for operation in compilation.ir.operations
            if operation.opcode is OpCode.RESET
        )

        self.assertIsNotNone(reset_operation.provenance)
        assert reset_operation.provenance is not None
        self.assertEqual(len(reset_operation.provenance.call_stack), 1)
        self.assertIsNotNone(result.classical_output)
        assert result.classical_output is not None
        self.assertEqual(result.classical_output.counts, (50, 0))

    def test_observations_inside_composed_callees_remain_unsupported(self) -> None:
        with self.assertRaises(PythonFrontendError) as captured:
            _calls_observation_helper.to_logical_module()

        diagnostic = captured.exception.diagnostics[0]
        self.assertEqual(diagnostic.code, "P116")
        self.assertIn("observations", diagnostic.message)

    def test_observation_result_cannot_drive_python_control_flow(self) -> None:
        with self.assertRaises(PythonFrontendError) as captured:
            _observation_branch.to_logical_program()

        self.assertEqual(captured.exception.diagnostics[0].code, "P102")

    def test_observation_result_cannot_be_used_as_a_quantum_gate_argument(self) -> None:
        with self.assertRaises(PythonFrontendError) as captured:
            _observation_as_gate_argument.to_logical_program()

        self.assertEqual(captured.exception.diagnostics[0].code, "P106")

    def test_inferred_terminal_observation_stays_inferred(self) -> None:
        program = _inferred_terminal_observation.to_logical_program()
        result = run(_inferred_terminal_observation)
        observation = program.instructions[-1]

        self.assertIsInstance(observation, Observation)
        self.assertEqual(observation.reason, ObservationReason.CLASSICAL_RETURN)
        self.assertIsNotNone(result.classical_output_distribution)
        assert result.classical_output_distribution is not None
        self._assert_probabilities(
            result.classical_output_distribution.probabilities,
            (0.5, 0.5),
        )

    def test_bell_exact_and_sampled_behavior_remain_correlated(self) -> None:
        exact = run(_bell)
        sampled = run(_bell, execution=SampledExecutionRequest(shots=200, seed=42))

        self.assertIsNotNone(exact.classical_output_distribution)
        assert exact.classical_output_distribution is not None
        self._assert_probabilities(
            exact.classical_output_distribution.probabilities,
            (0.5, 0.0, 0.0, 0.5),
        )
        self.assertIsNotNone(sampled.classical_output)
        assert sampled.classical_output is not None
        self.assertEqual(sampled.classical_output.counts[1], 0)
        self.assertEqual(sampled.classical_output.counts[2], 0)
        self.assertEqual(sum(sampled.classical_output.counts), 200)

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
