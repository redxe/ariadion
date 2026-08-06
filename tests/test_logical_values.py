from __future__ import annotations

import copy
import json
import re
import unittest
from dataclasses import fields
from pathlib import Path

import ariadion
import ariadion_language
import ariadion_semantics
from ariadion import Basis, Bit, Qubit, basis
from ariadion_core import (
    ClassicalBitId,
    IrOperationId,
    LogicalOperationId,
    LogicalQubitId,
    ProgramId,
    SnapshotOperationId,
    SourceNodeId,
    SourceOperationId,
    SyntaxNodeId,
)
from ariadion_semantics import (
    ClassicalBitValue,
    FunctionEffect,
    LogicalGateOpCode,
    LogicalGateOperation,
    LogicalProgram,
    LogicalQubitValue,
    Observation,
    ObservationResultValue,
    ObservationReason,
    ReturnValueKind,
    ReturnValueRef,
    ScalarReturn,
    TupleReturn,
)


ROOT = Path(__file__).resolve().parents[1]
_TARGET_LANGUAGE_DOCUMENTS = (
    ROOT / "specs" / "language.md",
    ROOT / "specs" / "syntax.md",
    ROOT / "docs" / "roadmap.md",
)


class LogicalValueTests(unittest.TestCase):
    def test_logical_identity_types_are_distinct_from_source_and_ir_identities(self) -> None:
        self.assertIsNot(ClassicalBitId, LogicalQubitId)
        self.assertIsNot(ClassicalBitId, LogicalOperationId)
        self.assertIsNot(ClassicalBitId, SnapshotOperationId)
        self.assertIsNot(ClassicalBitId, SourceOperationId)
        self.assertIsNot(LogicalQubitId, LogicalOperationId)
        self.assertIsNot(LogicalQubitId, SyntaxNodeId)
        self.assertIsNot(LogicalQubitId, SourceNodeId)
        self.assertIsNot(LogicalOperationId, SnapshotOperationId)
        self.assertIsNot(LogicalOperationId, IrOperationId)

    def test_qubit_construction_creates_distinct_logical_values(self) -> None:
        first = Qubit()
        second = Qubit()

        self.assertNotEqual(first, second)
        self.assertEqual(repr(first), "Qubit()")
        self.assertEqual(repr(second), "Qubit()")
        with self.assertRaises(TypeError):
            Qubit(0)  # type: ignore[call-arg]

    def test_qubit_has_no_public_allocation_fields(self) -> None:
        field_names = {field.name for field in fields(Qubit)}

        self.assertEqual(field_names, {"_logical_id"})
        for field_name in (
            "target",
            "index",
            "slot",
            "register",
            "width",
            "physical_index",
            "logic",
        ):
            self.assertFalse(hasattr(Qubit(), field_name))
        self.assertFalse(hasattr(ariadion, "qubit"))

    def test_aliasing_and_copying_preserve_one_logical_value(self) -> None:
        original = Qubit()
        alias = original

        self.assertIs(alias, original)
        self.assertIs(copy.copy(original), original)
        self.assertIs(copy.deepcopy(original), original)
        self.assertEqual(alias, original)

    def test_private_identity_factory_supports_internal_frontends(self) -> None:
        logical_id = LogicalQubitId("logical:frontend:value")
        first = Qubit._from_logical_id(logical_id)
        second = Qubit._from_logical_id(logical_id)

        self.assertEqual(first, second)
        self.assertEqual(repr(first), "Qubit()")

    def test_qubit_cannot_be_used_as_an_ordinary_boolean(self) -> None:
        with self.assertRaisesRegex(TypeError, "cannot be used as a Boolean"):
            bool(Qubit())

    def test_bit_is_a_distinct_classical_value(self) -> None:
        bit = Bit(True)

        self.assertIs(bool(bit), True)
        self.assertNotEqual(bit, True)
        self.assertNotEqual(bit, Qubit())
        self.assertEqual(bit.to_json(), '{"value":true}')
        with self.assertRaisesRegex(ValueError, "bit value must be bool"):
            Bit(1)  # type: ignore[arg-type]

    def test_logical_operations_reference_logical_ids_not_integer_targets(self) -> None:
        control_id = LogicalQubitId("logical:control")
        target_id = LogicalQubitId("logical:target")
        operation = LogicalGateOperation(
            LogicalOperationId("logical-operation:cx"),
            LogicalGateOpCode.CX,
            (target_id,),
            controls=(control_id,),
        )

        self.assertEqual(operation.targets, (target_id,))
        self.assertEqual(operation.controls, (control_id,))
        self.assertFalse(any(isinstance(value, int) for value in operation.targets))
        self.assertFalse(any(isinstance(value, int) for value in operation.controls))
        self.assertEqual(json.loads(operation.to_json()), operation.to_dict())

        single_qubit_operation = LogicalGateOperation(
            LogicalOperationId("logical-operation:h"),
            LogicalGateOpCode.H,
            (target_id,),
        )
        self.assertEqual(single_qubit_operation.controls, ())

        with self.assertRaisesRegex(ValueError, "logical operation targets"):
            LogicalGateOperation(
                LogicalOperationId("logical-operation:invalid"),
                LogicalGateOpCode.H,
                (0,),  # type: ignore[arg-type]
            )

    def test_observation_preserves_basis_and_reason(self) -> None:
        observation = Observation(
            LogicalOperationId("logical-operation:observe-left"),
            LogicalQubitId("logical:left"),
            ClassicalBitId("classical:left-result"),
            Basis("z"),
            ObservationReason.CLASSICAL_RETURN,
        )

        self.assertEqual(observation.basis.name, "z")
        self.assertEqual(observation.reason, ObservationReason.CLASSICAL_RETURN)
        self.assertEqual(
            observation.to_dict(),
            {
                "id": "logical-operation:observe-left",
                "qubit_id": "logical:left",
                "result_id": "classical:left-result",
                "basis": {"name": "z"},
                "reason": "classical_return",
                "source": None,
            },
        )
        self.assertEqual(json.loads(observation.to_json()), observation.to_dict())

    def test_logical_program_keeps_ordered_instructions_without_allocation_fields(self) -> None:
        left = LogicalQubitValue(LogicalQubitId("logical:left"), display_name="left")
        right = LogicalQubitValue(LogicalQubitId("logical:right"), display_name="right")
        left_result = ClassicalBitValue(
            ClassicalBitId("classical:left-result"),
            display_name="left_result",
        )
        h = LogicalGateOperation(
            LogicalOperationId("logical-operation:h"),
            LogicalGateOpCode.H,
            (left.id,),
        )
        cx = LogicalGateOperation(
            LogicalOperationId("logical-operation:cx"),
            LogicalGateOpCode.CX,
            (right.id,),
            controls=(left.id,),
        )
        observe = Observation(
            LogicalOperationId("logical-operation:observe-left"),
            left.id,
            left_result.id,
            Basis("z"),
            ObservationReason.PROGRAM_OUTPUT,
        )

        program = LogicalProgram(
            ProgramId("logical:bell"),
            "bell",
            (left, right),
            (h, cx, observe),
            (left_result,),
            TupleReturn(
                (
                    ScalarReturn(ReturnValueRef(ReturnValueKind.CLASSICAL_BIT, left_result.id)),
                    ScalarReturn(ReturnValueRef(ReturnValueKind.QUANTUM_VALUE, right.id)),
                )
            ),
        )

        self.assertEqual(program.instructions, (h, cx, observe))
        self.assertEqual(
            [instruction["id"] for instruction in program.to_dict()["instructions"]],
            ["logical-operation:h", "logical-operation:cx", "logical-operation:observe-left"],
        )
        self.assertFalse(hasattr(program, "qubit_count"))
        self.assertFalse(hasattr(program, "allocated_qubit_count"))
        self.assertEqual(program.outputs, (left_result.id, right.id))

    def test_logical_program_rejects_invalid_references_and_instruction_shapes(self) -> None:
        left = LogicalQubitValue(LogicalQubitId("logical:left"))
        unknown = LogicalQubitId("logical:unknown")
        result = ClassicalBitValue(ClassicalBitId("classical:left-result"))

        with self.assertRaisesRegex(ValueError, "undeclared logical qubit"):
            LogicalProgram(
                ProgramId("logical:unknown-reference"),
                "unknown-reference",
                (left,),
                (
                    LogicalGateOperation(
                        LogicalOperationId("logical-operation:h"),
                        LogicalGateOpCode.H,
                        (unknown,),
                    ),
                ),
            )
        with self.assertRaisesRegex(ValueError, "distinct control and target"):
            LogicalProgram(
                ProgramId("logical:invalid-cx"),
                "invalid-cx",
                (left,),
                (
                    LogicalGateOperation(
                        LogicalOperationId("logical-operation:cx"),
                        LogicalGateOpCode.CX,
                        (left.id,),
                        controls=(left.id,),
                    ),
                ),
            )
        with self.assertRaisesRegex(ValueError, "instruction IDs must be unique"):
            LogicalProgram(
                ProgramId("logical:duplicate-instruction"),
                "duplicate-instruction",
                (left,),
                (
                    LogicalGateOperation(
                        LogicalOperationId("logical-operation:duplicate"),
                        LogicalGateOpCode.H,
                        (left.id,),
                    ),
                    Observation(
                        LogicalOperationId("logical-operation:duplicate"),
                        left.id,
                        result.id,
                        Basis("z"),
                        ObservationReason.PROGRAM_OUTPUT,
                    ),
                ),
                (result,),
            )

    def test_classical_values_require_declared_unique_observation_producers(self) -> None:
        left = LogicalQubitValue(LogicalQubitId("logical:left"))
        right = LogicalQubitValue(LogicalQubitId("logical:right"))
        result = ClassicalBitValue(ClassicalBitId("classical:result"))
        first = Observation(
            LogicalOperationId("logical-operation:observe-left"),
            left.id,
            result.id,
            Basis("z"),
            ObservationReason.PROGRAM_OUTPUT,
        )
        duplicate = Observation(
            LogicalOperationId("logical-operation:observe-right"),
            right.id,
            result.id,
            Basis("z"),
            ObservationReason.PROGRAM_OUTPUT,
        )
        with self.assertRaisesRegex(ValueError, "observation result IDs must be unique"):
            LogicalProgram(
                ProgramId("logical:duplicate-results"),
                "duplicate-results",
                (left, right),
                (first, duplicate),
                (result,),
            )

        unknown_result = Observation(
            LogicalOperationId("logical-operation:unknown-result"),
            left.id,
            ClassicalBitId("classical:unknown"),
            Basis("z"),
            ObservationReason.PROGRAM_OUTPUT,
        )
        with self.assertRaisesRegex(ValueError, "undeclared classical bit"):
            LogicalProgram(
                ProgramId("logical:unknown-result"),
                "unknown-result",
                (left,),
                (unknown_result,),
                (result,),
            )

        return_shape = LogicalProgram(
            ProgramId("logical:output-order"),
            "output-order",
            (left, right),
            (first,),
            (result,),
            TupleReturn(
                (
                    ScalarReturn(ReturnValueRef(ReturnValueKind.QUANTUM_VALUE, right.id)),
                    ScalarReturn(ReturnValueRef(ReturnValueKind.CLASSICAL_BIT, result.id)),
                )
            ),
        )
        self.assertEqual(return_shape.outputs, (right.id, result.id))
        self.assertEqual(len(return_shape.instructions), 1)
        self.assertEqual(
            tuple(
                instruction.qubit_id
                for instruction in return_shape.instructions
                if isinstance(instruction, Observation)
            ),
            (left.id,),
        )

        with self.assertRaisesRegex(ValueError, "classical bit must have an observation"):
            LogicalProgram(
                ProgramId("logical:unproduced-output"),
                "unproduced-output",
                (left,),
                (),
                (result,),
                ScalarReturn(ReturnValueRef(ReturnValueKind.CLASSICAL_BIT, result.id)),
            )

        with self.assertRaisesRegex(ValueError, "classical bit must have an observation"):
            LogicalProgram(
                ProgramId("logical:discarded-unproduced"),
                "discarded-unproduced",
                (left,),
                (),
                (result,),
            )

    def test_classical_value_and_basis_namespace_contracts_are_immutable(self) -> None:
        value = ClassicalBitValue(
            ClassicalBitId("classical:left-result"),
            display_name="left_result",
        )
        self.assertEqual(
            value.to_dict(),
            {
                "id": "classical:left-result",
                "display_name": "left_result",
                "source": None,
            },
        )
        self.assertEqual(basis.x, Basis("x"))
        self.assertEqual(basis.y, Basis("y"))
        self.assertEqual(basis.z, Basis("z"))
        self.assertEqual(basis.named("custom"), Basis("custom"))
        self.assertIs(ariadion.basis, basis)
        self.assertIs(ariadion_language.basis, basis)
        self.assertFalse(hasattr(ariadion_semantics, "basis"))
        self.assertIs(ClassicalBitValue, ObservationResultValue)
        self.assertFalse(hasattr(ariadion, "x"))
        self.assertFalse(hasattr(ariadion, "y"))
        self.assertFalse(hasattr(ariadion, "z"))

    def test_logical_gate_opcodes_do_not_include_parameterless_rotations(self) -> None:
        self.assertEqual(
            {opcode.value for opcode in LogicalGateOpCode},
            {"x", "h", "z", "cx"},
        )

    def test_logical_values_and_effects_have_deterministic_contracts(self) -> None:
        value = LogicalQubitValue(
            LogicalQubitId("logical:left"),
            display_name="left",
        )

        self.assertEqual(
            value.to_json(),
            '{"display_name":"left","id":"logical:left","source":null}',
        )
        self.assertEqual(FunctionEffect.QUANTUM.value, "quantum")
        self.assertEqual(FunctionEffect.HYBRID.value, "hybrid")

    def test_target_documents_do_not_show_lowercase_qubit_construction(self) -> None:
        lowercase_constructor = re.compile(r"^\s*\w+\s*=\s*qubit\(\)", re.MULTILINE)
        lowercase_import = re.compile(r"from ariadion import .*\bqubit\b")

        for document in _TARGET_LANGUAGE_DOCUMENTS:
            contents = document.read_text(encoding="utf-8")
            self.assertIsNone(
                lowercase_constructor.search(contents),
                f"{document} contains a lowercase qubit constructor example",
            )
            self.assertIsNone(
                lowercase_import.search(contents),
                f"{document} imports a lowercase qubit factory",
            )


if __name__ == "__main__":
    unittest.main()
