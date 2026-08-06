from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from math import isfinite
from typing import Final, TypeAlias

from ariadion_core import SourceNodeId, SourceRange, canonical_json, require_nonempty_identifier


SYNTAX_AST_SCHEMA_VERSION: Final = 1
_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_INTEGER_PATTERN = re.compile(r"[0-9]+\Z")
_ANGLE_NUMBER_PATTERN = re.compile(r"[+-]?[0-9]+(?:\.[0-9]+)?\Z")


@dataclass(frozen=True, slots=True)
class SyntaxLocation:
    """A complete source span paired with a durable frontend node identity."""

    source_range: SourceRange
    source_node_id: SourceNodeId

    def __post_init__(self) -> None:
        _validate_source_range(self.source_range, label="syntax location")
        require_nonempty_identifier(self.source_node_id, label="syntax source node ID")

    def to_dict(self) -> dict[str, object]:
        return {
            "source_range": self.source_range.to_dict(),
            "source_node_id": self.source_node_id,
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class Identifier:
    """An author-written identifier, kept separate from later symbol resolution."""

    spelling: str
    location: SyntaxLocation

    def __post_init__(self) -> None:
        if not isinstance(self.spelling, str) or not _IDENTIFIER_PATTERN.fullmatch(
            self.spelling,
        ):
            raise ValueError("identifier spelling must match [A-Za-z_][A-Za-z0-9_]*")
        _validate_location(self.location, label="identifier")

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": "identifier",
            "spelling": self.spelling,
            "location": self.location.to_dict(),
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class IntegerLiteral:
    """A non-negative integer spelling retained for later semantic validation."""

    spelling: str
    location: SyntaxLocation

    def __post_init__(self) -> None:
        if not isinstance(self.spelling, str) or not _INTEGER_PATTERN.fullmatch(
            self.spelling,
        ):
            raise ValueError("integer literal spelling must contain decimal digits")
        _validate_location(self.location, label="integer literal")

    @property
    def value(self) -> int:
        return int(self.spelling)

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": "integer_literal",
            "spelling": self.spelling,
            "value": self.value,
            "location": self.location.to_dict(),
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


class AngleLiteralUnit(str, Enum):
    """Native-language angle suffixes; these are not canonical radians."""

    DEGREES = "deg"
    RADIANS = "rad"
    TURNS = "turns"


@dataclass(frozen=True, slots=True)
class AngleLiteral:
    """An author-written finite angle literal such as ``90deg`` or ``0.5turns``."""

    spelling: str
    unit: AngleLiteralUnit
    location: SyntaxLocation

    def __post_init__(self) -> None:
        if not isinstance(self.unit, AngleLiteralUnit):
            raise ValueError("angle literal unit must be AngleLiteralUnit")
        if not isinstance(self.spelling, str) or not self.spelling.endswith(self.unit.value):
            raise ValueError("angle literal spelling must end with its unit suffix")
        numeric_text = self.spelling.removesuffix(self.unit.value)
        if not _ANGLE_NUMBER_PATTERN.fullmatch(numeric_text):
            raise ValueError("angle literal spelling must contain a decimal number and unit")
        if not isfinite(float(numeric_text)):
            raise ValueError("angle literal value must be finite")
        _validate_location(self.location, label="angle literal")

    @property
    def numeric_text(self) -> str:
        return self.spelling.removesuffix(self.unit.value)

    @property
    def value(self) -> float:
        return float(self.numeric_text)

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": "angle_literal",
            "spelling": self.spelling,
            "value": self.value,
            "unit": self.unit.value,
            "location": self.location.to_dict(),
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class QubitReference:
    """A written register/index reference, not a lowered global qubit index."""

    register: Identifier
    index: IntegerLiteral
    location: SyntaxLocation

    def __post_init__(self) -> None:
        if not isinstance(self.register, Identifier):
            raise ValueError("qubit reference register must be Identifier")
        if not isinstance(self.index, IntegerLiteral):
            raise ValueError("qubit reference index must be IntegerLiteral")
        _validate_location(self.location, label="qubit reference")

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": "qubit_reference",
            "register": self.register.to_dict(),
            "index": self.index.to_dict(),
            "location": self.location.to_dict(),
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class QubitDeclaration:
    """The initial fixed-width `qubits N` declaration syntax node."""

    count: IntegerLiteral
    location: SyntaxLocation

    def __post_init__(self) -> None:
        if not isinstance(self.count, IntegerLiteral):
            raise ValueError("qubit declaration count must be IntegerLiteral")
        _validate_location(self.location, label="qubit declaration")

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": "qubit_declaration",
            "count": self.count.to_dict(),
            "location": self.location.to_dict(),
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


class PrimitiveGate(str, Enum):
    """Currently supported non-rotation gate spellings."""

    X = "x"
    H = "h"
    Z = "z"
    CX = "cx"


@dataclass(frozen=True, slots=True)
class GateStatement:
    """A non-rotation primitive gate statement with written qubit operands."""

    gate: PrimitiveGate
    operands: tuple[QubitReference, ...]
    location: SyntaxLocation

    def __post_init__(self) -> None:
        if not isinstance(self.gate, PrimitiveGate):
            raise ValueError("gate statement gate must be PrimitiveGate")
        if not isinstance(self.operands, tuple) or not all(
            isinstance(operand, QubitReference) for operand in self.operands
        ):
            raise ValueError("gate statement operands must be QubitReference values in a tuple")
        expected_operand_count = 2 if self.gate is PrimitiveGate.CX else 1
        if len(self.operands) != expected_operand_count:
            raise ValueError(
                f"{self.gate.value} expects {expected_operand_count} qubit operand(s)"
            )
        _validate_location(self.location, label="gate statement")

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": "gate_statement",
            "gate": self.gate.value,
            "operands": [operand.to_dict() for operand in self.operands],
            "location": self.location.to_dict(),
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


class RotationAxis(str, Enum):
    """Axes encoded by the native `rx`, `ry`, and `rz` spellings."""

    X = "x"
    Y = "y"
    Z = "z"


@dataclass(frozen=True, slots=True)
class RotationStatement:
    """A rotation statement retaining its target reference and source angle spelling."""

    axis: RotationAxis
    target: QubitReference
    angle: AngleLiteral
    location: SyntaxLocation

    def __post_init__(self) -> None:
        if not isinstance(self.axis, RotationAxis):
            raise ValueError("rotation statement axis must be RotationAxis")
        if not isinstance(self.target, QubitReference):
            raise ValueError("rotation statement target must be QubitReference")
        if not isinstance(self.angle, AngleLiteral):
            raise ValueError("rotation statement angle must be AngleLiteral")
        _validate_location(self.location, label="rotation statement")

    @property
    def gate_spelling(self) -> str:
        return f"r{self.axis.value}"

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": "rotation_statement",
            "axis": self.axis.value,
            "gate_spelling": self.gate_spelling,
            "target": self.target.to_dict(),
            "angle": self.angle.to_dict(),
            "location": self.location.to_dict(),
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class MeasurementStatement:
    """A written measurement target and result-key destination."""

    target: QubitReference
    result_key: Identifier
    location: SyntaxLocation

    def __post_init__(self) -> None:
        if not isinstance(self.target, QubitReference):
            raise ValueError("measurement target must be QubitReference")
        if not isinstance(self.result_key, Identifier):
            raise ValueError("measurement result_key must be Identifier")
        _validate_location(self.location, label="measurement statement")

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": "measurement_statement",
            "target": self.target.to_dict(),
            "result_key": self.result_key.to_dict(),
            "location": self.location.to_dict(),
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


ProgramItem: TypeAlias = (
    QubitDeclaration | GateStatement | RotationStatement | MeasurementStatement
)


@dataclass(frozen=True, slots=True)
class ProgramSyntax:
    """Immutable source AST root for one native Ariadion program."""

    name: Identifier
    items: tuple[ProgramItem, ...]
    location: SyntaxLocation

    def __post_init__(self) -> None:
        if not isinstance(self.name, Identifier):
            raise ValueError("program syntax name must be Identifier")
        if not isinstance(self.items, tuple) or not all(
            isinstance(
                item,
                (QubitDeclaration, GateStatement, RotationStatement, MeasurementStatement),
            )
            for item in self.items
        ):
            raise ValueError("program syntax items must be AST items in a tuple")
        _validate_location(self.location, label="program syntax")
        _validate_unique_node_ids(self)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": SYNTAX_AST_SCHEMA_VERSION,
            "kind": "program",
            "name": self.name.to_dict(),
            "items": [item.to_dict() for item in self.items],
            "location": self.location.to_dict(),
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


class SyntaxDiagnosticSeverity(str, Enum):
    """Severity for parser and lexer diagnostics, independent of semantic diagnostics."""

    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True, slots=True)
class SyntaxDiagnostic:
    """A source-only diagnostic emitted before name resolution or lowering."""

    code: str
    message: str
    source_range: SourceRange
    severity: SyntaxDiagnosticSeverity = SyntaxDiagnosticSeverity.ERROR

    def __post_init__(self) -> None:
        if not isinstance(self.code, str) or not self.code:
            raise ValueError("syntax diagnostic code must be a non-empty string")
        if not isinstance(self.message, str) or not self.message:
            raise ValueError("syntax diagnostic message must be a non-empty string")
        _validate_source_range(self.source_range, label="syntax diagnostic")
        if not isinstance(self.severity, SyntaxDiagnosticSeverity):
            raise ValueError("syntax diagnostic severity must be SyntaxDiagnosticSeverity")

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": self.message,
            "severity": self.severity.value,
            "source_range": self.source_range.to_dict(),
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


def _validate_location(value: SyntaxLocation, *, label: str) -> None:
    if not isinstance(value, SyntaxLocation):
        raise ValueError(f"{label} location must be SyntaxLocation")


def _validate_source_range(value: SourceRange, *, label: str) -> None:
    if not isinstance(value, SourceRange):
        raise ValueError(f"{label} source_range must be SourceRange")
    if (
        value.line is None
        or value.column is None
        or value.end_line is None
        or value.end_column is None
    ):
        raise ValueError(f"{label} source_range must include a complete source span")


def _validate_unique_node_ids(program: ProgramSyntax) -> None:
    seen: set[SourceNodeId] = set()
    for location in _iter_locations(program):
        if location.source_node_id in seen:
            raise ValueError("syntax source node IDs must be unique within a program")
        seen.add(location.source_node_id)


def _iter_locations(program: ProgramSyntax) -> tuple[SyntaxLocation, ...]:
    locations: list[SyntaxLocation] = [program.location, program.name.location]
    for item in program.items:
        locations.append(item.location)
        if isinstance(item, QubitDeclaration):
            locations.append(item.count.location)
        elif isinstance(item, GateStatement):
            for operand in item.operands:
                locations.extend(
                    (operand.location, operand.register.location, operand.index.location)
                )
        elif isinstance(item, RotationStatement):
            locations.extend(
                (
                    item.target.location,
                    item.target.register.location,
                    item.target.index.location,
                    item.angle.location,
                )
            )
        else:
            locations.extend(
                (
                    item.target.location,
                    item.target.register.location,
                    item.target.index.location,
                    item.result_key.location,
                )
            )
    return tuple(locations)
