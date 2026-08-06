from __future__ import annotations

import json
import unittest

from ariadion_core import SourceNodeId, SourceRange
from ariadion_syntax import (
    AngleLiteral,
    AngleLiteralUnit,
    GateStatement,
    Identifier,
    IntegerLiteral,
    MeasurementStatement,
    PrimitiveGate,
    ProgramSyntax,
    QubitDeclaration,
    QubitReference,
    RotationAxis,
    RotationStatement,
    SyntaxDiagnostic,
    SyntaxDiagnosticSeverity,
    SyntaxLocation,
    Token,
    TokenKind,
)


class SyntaxAstTests(unittest.TestCase):
    def test_bell_ast_preserves_written_references_and_serializes_canonically(self) -> None:
        program = ProgramSyntax(
            name=self._identifier("bell", "program:name", 1, 9),
            items=(
                QubitDeclaration(
                    self._integer("2", "qubits:count", 3, 8),
                    self._location("qubits", 3, 1, 9),
                ),
                GateStatement(
                    PrimitiveGate.H,
                    (self._qubit("h:target", 5, 3),),
                    self._location("h", 5, 1, 7),
                ),
                GateStatement(
                    PrimitiveGate.CX,
                    (
                        self._qubit("cx:control", 6, 4),
                        self._qubit("cx:target", 6, 10, index="1"),
                    ),
                    self._location("cx", 6, 1, 15),
                ),
                MeasurementStatement(
                    self._qubit("measure:target", 7, 9),
                    self._identifier("result", "measure:key", 7, 17),
                    self._location("measure", 7, 1, 23),
                ),
            ),
            location=self._location("program", 1, 1, 23),
        )

        payload = program.to_dict()
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["name"]["spelling"], "bell")
        self.assertEqual(payload["items"][0]["kind"], "qubit_declaration")
        self.assertEqual(payload["items"][1]["gate"], "h")
        self.assertEqual(payload["items"][2]["operands"][0]["register"]["spelling"], "q")
        self.assertEqual(payload["items"][2]["operands"][1]["index"]["value"], 1)
        self.assertEqual(payload["items"][3]["result_key"]["spelling"], "result")
        self.assertEqual(json.loads(program.to_json()), payload)

    def test_rotation_ast_preserves_angle_suffixes_without_canonicalizing(self) -> None:
        first_angle = AngleLiteral(
            "90deg",
            AngleLiteralUnit.DEGREES,
            self._location("ry:angle", 5, 10, 15),
        )
        second_angle = AngleLiteral(
            "0.5turns",
            AngleLiteralUnit.TURNS,
            self._location("rz:angle", 6, 10, 18),
        )
        program = ProgramSyntax(
            name=self._identifier("rotations", "program:name", 1, 9),
            items=(
                QubitDeclaration(
                    self._integer("1", "qubits:count", 3, 8),
                    self._location("qubits", 3, 1, 9),
                ),
                RotationStatement(
                    RotationAxis.Y,
                    self._qubit("ry:target", 5, 4),
                    first_angle,
                    self._location("ry", 5, 1, 15),
                ),
                RotationStatement(
                    RotationAxis.Z,
                    self._qubit("rz:target", 6, 4),
                    second_angle,
                    self._location("rz", 6, 1, 18),
                ),
            ),
            location=self._location("program", 1, 1, 26),
        )

        first_rotation = program.items[1]
        second_rotation = program.items[2]
        self.assertIsInstance(first_rotation, RotationStatement)
        self.assertIsInstance(second_rotation, RotationStatement)
        assert isinstance(first_rotation, RotationStatement)
        assert isinstance(second_rotation, RotationStatement)
        self.assertEqual(first_rotation.gate_spelling, "ry")
        self.assertEqual(first_angle.spelling, "90deg")
        self.assertEqual(first_angle.numeric_text, "90")
        self.assertEqual(first_angle.value, 90.0)
        self.assertEqual(second_rotation.gate_spelling, "rz")
        self.assertEqual(second_angle.spelling, "0.5turns")
        self.assertEqual(second_angle.unit, AngleLiteralUnit.TURNS)
        self.assertEqual(second_angle.value, 0.5)
        self.assertNotIn("radians", second_angle.to_dict())

    def test_tokens_and_syntax_diagnostics_are_source_only_contracts(self) -> None:
        source_range = SourceRange(
            file="examples/bell.ari",
            line=5,
            column=1,
            end_line=5,
            end_column=2,
        )
        token = Token(TokenKind.H, "h", source_range)
        eof = Token(TokenKind.EOF, "", source_range)
        diagnostic = SyntaxDiagnostic(
            code="S001",
            message="expected a qubit reference",
            source_range=source_range,
        )

        self.assertEqual(token.to_dict()["kind"], "h")
        self.assertEqual(token.to_dict()["spelling"], "h")
        self.assertEqual(eof.to_dict()["spelling"], "")
        self.assertEqual(diagnostic.severity, SyntaxDiagnosticSeverity.ERROR)
        self.assertEqual(diagnostic.to_dict()["code"], "S001")
        self.assertEqual(json.loads(diagnostic.to_json())["source_range"]["line"], 5)

    def test_ast_contract_rejects_incomplete_locations_and_invalid_combinations(self) -> None:
        with self.assertRaisesRegex(ValueError, "complete source span"):
            SyntaxLocation(
                SourceRange(file="examples/invalid.ari", line=1),
                SourceNodeId("invalid:location"),
            )

        with self.assertRaisesRegex(ValueError, "complete source span"):
            Token(
                TokenKind.H,
                "h",
                SourceRange(file="examples/invalid.ari", line=1),
            )

        with self.assertRaisesRegex(ValueError, "end with its unit suffix"):
            AngleLiteral(
                "90rad",
                AngleLiteralUnit.DEGREES,
                self._location("invalid:angle", 1, 1, 6),
            )

        qubit = self._qubit("invalid:target", 1, 3)
        with self.assertRaisesRegex(ValueError, "cx expects 2"):
            GateStatement(
                PrimitiveGate.CX,
                (qubit,),
                self._location("invalid:cx", 1, 1, 7),
            )

        name = self._identifier("duplicate", "duplicate:id", 1, 9)
        declaration = QubitDeclaration(
            self._integer("1", "duplicate:count", 3, 8),
            self._location("duplicate:id", 3, 1, 9),
        )
        with self.assertRaisesRegex(ValueError, "must be unique"):
            ProgramSyntax(
                name=name,
                items=(declaration,),
                location=self._location("duplicate:program", 1, 1, 18),
            )

    def _qubit(
        self,
        prefix: str,
        line: int,
        column: int,
        *,
        index: str = "0",
    ) -> QubitReference:
        return QubitReference(
            register=self._identifier("q", f"{prefix}:register", line, column),
            index=self._integer(index, f"{prefix}:index", line, column + 2),
            location=self._location(prefix, line, column, column + 4),
        )

    def _identifier(self, spelling: str, node_id: str, line: int, column: int) -> Identifier:
        return Identifier(
            spelling,
            self._location(node_id, line, column, column + len(spelling)),
        )

    def _integer(self, spelling: str, node_id: str, line: int, column: int) -> IntegerLiteral:
        return IntegerLiteral(
            spelling,
            self._location(node_id, line, column, column + len(spelling)),
        )

    def _location(
        self,
        node_id: str,
        line: int,
        column: int,
        end_column: int,
    ) -> SyntaxLocation:
        return SyntaxLocation(
            SourceRange(
                file="examples/test.ari",
                line=line,
                column=column,
                end_line=line,
                end_column=end_column,
            ),
            SourceNodeId(node_id),
        )


if __name__ == "__main__":
    unittest.main()
