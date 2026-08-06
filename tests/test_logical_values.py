from __future__ import annotations

import copy
import json
import re
import unittest
from dataclasses import fields
from pathlib import Path

import ariadion
from ariadion import Bit, Qubit
from ariadion_core import (
    IrOperationId,
    LogicalOperationId,
    LogicalQubitId,
    SnapshotOperationId,
    SourceNodeId,
    SyntaxNodeId,
)
from ariadion_semantics import (
    Basis,
    FunctionEffect,
    LogicalOpCode,
    LogicalOperation,
    LogicalQubitValue,
    Observation,
    ObservationReason,
)


ROOT = Path(__file__).resolve().parents[1]
_TARGET_LANGUAGE_DOCUMENTS = (
    ROOT / "specs" / "language.md",
    ROOT / "specs" / "syntax.md",
    ROOT / "docs" / "roadmap.md",
)


class LogicalValueTests(unittest.TestCase):
    def test_logical_identity_types_are_distinct_from_source_and_ir_identities(self) -> None:
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
        operation = LogicalOperation(
            LogicalOperationId("logical-operation:cx"),
            LogicalOpCode.CX,
            (target_id,),
            controls=(control_id,),
        )

        self.assertEqual(operation.targets, (target_id,))
        self.assertEqual(operation.controls, (control_id,))
        self.assertFalse(any(isinstance(value, int) for value in operation.targets))
        self.assertFalse(any(isinstance(value, int) for value in operation.controls))
        self.assertEqual(json.loads(operation.to_json()), operation.to_dict())

        single_qubit_operation = LogicalOperation(
            LogicalOperationId("logical-operation:h"),
            LogicalOpCode.H,
            (target_id,),
        )
        self.assertEqual(single_qubit_operation.controls, ())

        with self.assertRaisesRegex(ValueError, "logical operation targets"):
            LogicalOperation(
                LogicalOperationId("logical-operation:invalid"),
                LogicalOpCode.H,
                (0,),  # type: ignore[arg-type]
            )

    def test_observation_preserves_basis_and_reason(self) -> None:
        observation = Observation(
            LogicalQubitId("logical:left"),
            Basis("z"),
            ObservationReason.CLASSICAL_RETURN,
        )

        self.assertEqual(observation.basis.name, "z")
        self.assertEqual(observation.reason, ObservationReason.CLASSICAL_RETURN)
        self.assertEqual(
            observation.to_dict(),
            {
                "qubit_id": "logical:left",
                "basis": {"name": "z"},
                "reason": "classical_return",
                "source": None,
            },
        )
        self.assertEqual(json.loads(observation.to_json()), observation.to_dict())

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
