from __future__ import annotations

import json
import unittest

from ariadion_cli.trace_view import render_logical_run_summary
from ariadion_core import ClassicalBitId, LogicalOperationId, LogicalQubitId, ProgramId
from ariadion_language import basis
from ariadion_runtime import TraceCaptureOptions, run_logical_program
from ariadion_semantics import (
    LogicalGateOpCode,
    LogicalGateOperation,
    LogicalProgram,
    LogicalQubitValue,
    NoReturn,
    Observation,
    ObservationReason,
    ObservationResultValue,
    ReturnShape,
    ReturnValueKind,
    ReturnValueRef,
    ScalarReturn,
    TupleReturn,
)
from daidalon import compile_logical_program


class ReturnShapeTests(unittest.TestCase):
    def test_scalar_classical_return_preserves_its_tagged_leaf(self) -> None:
        program, left_result, _ = self._classical_program(
            self._classical_scalar("classical:returns:left")
        )

        self.assertEqual(program.outputs, (left_result.id,))
        self.assertEqual(
            program.to_dict()["return_shape"],
            {
                "kind": "scalar",
                "value": {
                    "kind": "classical_bit",
                    "value_id": "classical:returns:left",
                },
            },
        )

    def test_one_element_classical_tuple_is_not_a_scalar_return(self) -> None:
        scalar = self._classical_scalar("classical:returns:left")
        tuple_shape = TupleReturn((scalar,))
        program, left_result, _ = self._classical_program(tuple_shape)

        self.assertNotEqual(tuple_shape, scalar)
        self.assertEqual(program.outputs, (left_result.id,))
        self.assertEqual(
            program.to_dict()["return_shape"],
            {
                "kind": "tuple",
                "items": [
                    {
                        "kind": "scalar",
                        "value": {
                            "kind": "classical_bit",
                            "value_id": "classical:returns:left",
                        },
                    }
                ],
            },
        )

    def test_two_element_classical_tuple_keeps_left_to_right_order(self) -> None:
        shape = TupleReturn(
            (
                self._classical_scalar("classical:returns:left"),
                self._classical_scalar("classical:returns:right"),
            )
        )
        program, left_result, right_result = self._classical_program(shape)
        compilation = compile_logical_program(program)

        self.assertEqual(program.outputs, (left_result.id, right_result.id))
        self.assertEqual(
            compilation.readout.classical_return_ids(),
            (left_result.id, right_result.id),
        )

    def test_nested_tuple_return_preserves_nested_structure(self) -> None:
        left = LogicalQubitValue(LogicalQubitId("logical:nested:left"), "left")
        right = LogicalQubitValue(LogicalQubitId("logical:nested:right"), "right")
        quantum = LogicalQubitValue(LogicalQubitId("logical:nested:quantum"), "target")
        left_result = ObservationResultValue(
            ClassicalBitId("classical:nested:left"),
            "left_result",
        )
        right_result = ObservationResultValue(
            ClassicalBitId("classical:nested:right"),
            "right_result",
        )
        shape = TupleReturn(
            (
                ScalarReturn(ReturnValueRef(ReturnValueKind.CLASSICAL_BIT, left_result.id)),
                TupleReturn(
                    (
                        ScalarReturn(
                            ReturnValueRef(ReturnValueKind.CLASSICAL_BIT, right_result.id)
                        ),
                        ScalarReturn(
                            ReturnValueRef(ReturnValueKind.QUANTUM_VALUE, quantum.id)
                        ),
                    )
                ),
            )
        )
        program = LogicalProgram(
            ProgramId("logical:nested"),
            "nested",
            (left, right, quantum),
            (
                Observation(
                    LogicalOperationId("logical-op:nested:observe-left"),
                    left.id,
                    left_result.id,
                    basis.z,
                    ObservationReason.CLASSICAL_RETURN,
                ),
                Observation(
                    LogicalOperationId("logical-op:nested:observe-right"),
                    right.id,
                    right_result.id,
                    basis.z,
                    ObservationReason.CLASSICAL_RETURN,
                ),
            ),
            (left_result, right_result),
            shape,
        )

        self.assertEqual(program.outputs, (left_result.id, right_result.id, quantum.id))
        self.assertEqual(program.to_dict()["return_shape"]["items"][1]["kind"], "tuple")
        self.assertEqual(
            program.to_dict()["return_shape"]["items"][1]["items"][1]["value"]["kind"],
            "quantum_value",
        )

    def test_scalar_quantum_return_is_not_observed(self) -> None:
        target = LogicalQubitValue(LogicalQubitId("logical:quantum:return"), "target")
        shape = ScalarReturn(
            ReturnValueRef(ReturnValueKind.QUANTUM_VALUE, target.id)
        )
        program = LogicalProgram(
            ProgramId("logical:quantum-return"),
            "quantum-return",
            (target,),
            (
                LogicalGateOperation(
                    LogicalOperationId("logical-op:quantum-return:h"),
                    LogicalGateOpCode.H,
                    (target.id,),
                ),
            ),
            return_shape=shape,
        )

        execution = run_logical_program(program)

        self.assertIsNone(execution.classical_output_distribution)
        self.assertEqual(execution.return_shape, shape)
        self.assertEqual(
            execution.returned_quantum_values[0].logical_qubit_id,
            target.id,
        )
        self.assertEqual(execution.returned_quantum_values[0].allocated_slot, 0)
        self.assertEqual(execution.returned_quantum_values[0].display_name, "target")

    def test_mixed_return_exposes_classical_distribution_and_quantum_handle(self) -> None:
        classical = LogicalQubitValue(LogicalQubitId("logical:mixed:classical"), "left")
        quantum = LogicalQubitValue(LogicalQubitId("logical:mixed:quantum"), "right")
        result = ObservationResultValue(ClassicalBitId("classical:mixed:left"), "left_result")
        shape = TupleReturn(
            (
                ScalarReturn(ReturnValueRef(ReturnValueKind.CLASSICAL_BIT, result.id)),
                ScalarReturn(ReturnValueRef(ReturnValueKind.QUANTUM_VALUE, quantum.id)),
            )
        )
        program = LogicalProgram(
            ProgramId("logical:mixed-return"),
            "mixed-return",
            (classical, quantum),
            (
                LogicalGateOperation(
                    LogicalOperationId("logical-op:mixed:h-left"),
                    LogicalGateOpCode.H,
                    (classical.id,),
                ),
                LogicalGateOperation(
                    LogicalOperationId("logical-op:mixed:h-right"),
                    LogicalGateOpCode.H,
                    (quantum.id,),
                ),
                Observation(
                    LogicalOperationId("logical-op:mixed:observe-left"),
                    classical.id,
                    result.id,
                    basis.z,
                    ObservationReason.CLASSICAL_RETURN,
                ),
            ),
            (result,),
            shape,
        )

        execution = run_logical_program(program)

        self.assertIsNotNone(execution.classical_output_distribution)
        assert execution.classical_output_distribution is not None
        self.assertEqual(execution.classical_output_distribution.result_ids, (result.id,))
        self.assertAlmostEqual(execution.classical_output_distribution.probabilities[0], 0.5)
        self.assertAlmostEqual(execution.classical_output_distribution.probabilities[1], 0.5)
        self.assertEqual(
            tuple(value.logical_qubit_id for value in execution.returned_quantum_values),
            (quantum.id,),
        )
        self.assertEqual(execution.return_shape, shape)

    def test_no_return_produces_no_public_return_values(self) -> None:
        program, _, _ = self._classical_program(NoReturn())
        execution = run_logical_program(program)

        self.assertEqual(program.outputs, ())
        self.assertIsNone(execution.classical_output_distribution)
        self.assertEqual(execution.returned_quantum_values, ())

    def test_unknown_classical_return_reference_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "undeclared observation result"):
            self._classical_program(
                self._classical_scalar("classical:returns:unknown")
            )

    def test_unknown_quantum_return_reference_is_rejected(self) -> None:
        unknown = ScalarReturn(
            ReturnValueRef(
                ReturnValueKind.QUANTUM_VALUE,
                LogicalQubitId("logical:returns:unknown"),
            )
        )

        with self.assertRaisesRegex(ValueError, "undeclared logical qubit"):
            self._classical_program(unknown)

    def test_return_kind_and_identifier_mismatches_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "classical return kind cannot reference"):
            self._classical_program(
                ScalarReturn(
                    ReturnValueRef(
                        ReturnValueKind.CLASSICAL_BIT,
                        LogicalQubitId("logical:returns:left"),
                    )
                )
            )
        with self.assertRaisesRegex(ValueError, "quantum return kind cannot reference"):
            self._classical_program(
                ScalarReturn(
                    ReturnValueRef(
                        ReturnValueKind.QUANTUM_VALUE,
                        ClassicalBitId("classical:returns:left"),
                    )
                )
            )

    def test_quantum_return_cannot_refer_to_an_observed_value(self) -> None:
        with self.assertRaisesRegex(ValueError, "cannot reference an observed"):
            self._classical_program(
                ScalarReturn(
                    ReturnValueRef(
                        ReturnValueKind.QUANTUM_VALUE,
                        LogicalQubitId("logical:returns:left"),
                    )
                )
            )

    def test_recursive_return_serialization_is_stable(self) -> None:
        shape = TupleReturn(
            (
                self._classical_scalar("classical:returns:left"),
                TupleReturn((self._classical_scalar("classical:returns:right"),)),
            )
        )
        program, _, _ = self._classical_program(shape)

        self.assertEqual(program.to_json(), program.to_json())
        self.assertEqual(json.loads(program.to_json()), program.to_dict())

    def test_readout_flattens_classical_and_quantum_leaves_independently(self) -> None:
        classical = LogicalQubitValue(LogicalQubitId("logical:flatten:classical"))
        quantum = LogicalQubitValue(LogicalQubitId("logical:flatten:quantum"))
        result = ObservationResultValue(ClassicalBitId("classical:flatten:left"))
        shape = TupleReturn(
            (
                TupleReturn(
                    (
                        ScalarReturn(ReturnValueRef(ReturnValueKind.QUANTUM_VALUE, quantum.id)),
                        ScalarReturn(ReturnValueRef(ReturnValueKind.CLASSICAL_BIT, result.id)),
                    )
                ),
                ScalarReturn(ReturnValueRef(ReturnValueKind.QUANTUM_VALUE, quantum.id)),
                ScalarReturn(ReturnValueRef(ReturnValueKind.CLASSICAL_BIT, result.id)),
            )
        )
        program = LogicalProgram(
            ProgramId("logical:flatten"),
            "flatten",
            (classical, quantum),
            (
                Observation(
                    LogicalOperationId("logical-op:flatten:observe"),
                    classical.id,
                    result.id,
                    basis.z,
                    ObservationReason.CLASSICAL_RETURN,
                ),
            ),
            (result,),
            shape,
        )
        readout = compile_logical_program(program).readout

        self.assertEqual(readout.classical_return_ids(), (result.id, result.id))
        self.assertEqual(readout.quantum_return_ids(), (quantum.id, quantum.id))

    def test_repeated_return_leaves_are_preserved_as_explicit_aliases(self) -> None:
        shape = TupleReturn(
            (
                self._classical_scalar("classical:returns:left"),
                self._classical_scalar("classical:returns:left"),
            )
        )
        program, left_result, _ = self._classical_program(shape)
        distribution = run_logical_program(program).classical_output_distribution

        self.assertEqual(program.outputs, (left_result.id, left_result.id))
        self.assertIsNotNone(distribution)
        assert distribution is not None
        self.assertEqual(distribution.result_ids, (left_result.id, left_result.id))
        self.assertAlmostEqual(distribution.probabilities[0], 0.5)
        self.assertAlmostEqual(distribution.probabilities[3], 0.5)

    def test_logical_summary_renders_the_joint_bell_distribution(self) -> None:
        left = LogicalQubitValue(LogicalQubitId("logical:bell:left"), "left")
        right = LogicalQubitValue(LogicalQubitId("logical:bell:right"), "right")
        left_result = ObservationResultValue(ClassicalBitId("classical:bell:left"), "left_result")
        right_result = ObservationResultValue(
            ClassicalBitId("classical:bell:right"),
            "right_result",
        )
        program = LogicalProgram(
            ProgramId("logical:bell-summary"),
            "bell-summary",
            (left, right),
            (
                LogicalGateOperation(
                    LogicalOperationId("logical-op:bell-summary:h"),
                    LogicalGateOpCode.H,
                    (left.id,),
                ),
                LogicalGateOperation(
                    LogicalOperationId("logical-op:bell-summary:cx"),
                    LogicalGateOpCode.CX,
                    (right.id,),
                    controls=(left.id,),
                ),
                Observation(
                    LogicalOperationId("logical-op:bell-summary:observe-left"),
                    left.id,
                    left_result.id,
                    basis.z,
                    ObservationReason.CLASSICAL_RETURN,
                ),
                Observation(
                    LogicalOperationId("logical-op:bell-summary:observe-right"),
                    right.id,
                    right_result.id,
                    basis.z,
                    ObservationReason.CLASSICAL_RETURN,
                ),
            ),
            (left_result, right_result),
            TupleReturn(
                (
                    ScalarReturn(ReturnValueRef(ReturnValueKind.CLASSICAL_BIT, left_result.id)),
                    ScalarReturn(ReturnValueRef(ReturnValueKind.CLASSICAL_BIT, right_result.id)),
                )
            ),
        )

        rendered = render_logical_run_summary(run_logical_program(program))

        self.assertIn("Returned classical distribution:", rendered)
        self.assertIn("left_result=0, right_result=0: 0.500000", rendered)
        self.assertIn("left_result=0, right_result=1: 0.000000", rendered)
        self.assertIn("left_result=1, right_result=0: 0.000000", rendered)
        self.assertIn("left_result=1, right_result=1: 0.500000", rendered)

    def _classical_program(
        self,
        return_shape: ReturnShape,
    ) -> tuple[LogicalProgram, ObservationResultValue, ObservationResultValue]:
        left = LogicalQubitValue(LogicalQubitId("logical:returns:left"), "left")
        right = LogicalQubitValue(LogicalQubitId("logical:returns:right"), "right")
        left_result = ObservationResultValue(
            ClassicalBitId("classical:returns:left"),
            "left_result",
        )
        right_result = ObservationResultValue(
            ClassicalBitId("classical:returns:right"),
            "right_result",
        )
        program = LogicalProgram(
            ProgramId("logical:returns"),
            "returns",
            (left, right),
            (
                LogicalGateOperation(
                    LogicalOperationId("logical-op:returns:h"),
                    LogicalGateOpCode.H,
                    (left.id,),
                ),
                Observation(
                    LogicalOperationId("logical-op:returns:observe-left"),
                    left.id,
                    left_result.id,
                    basis.z,
                    ObservationReason.CLASSICAL_RETURN,
                ),
                Observation(
                    LogicalOperationId("logical-op:returns:observe-right"),
                    right.id,
                    right_result.id,
                    basis.z,
                    ObservationReason.CLASSICAL_RETURN,
                ),
            ),
            (left_result, right_result),
            return_shape,
        )
        return program, left_result, right_result

    @staticmethod
    def _classical_scalar(result_id: str) -> ScalarReturn:
        return ScalarReturn(
            ReturnValueRef(ReturnValueKind.CLASSICAL_BIT, ClassicalBitId(result_id))
        )


if __name__ == "__main__":
    unittest.main()
