from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ariadion_core import SourceRange, canonical_json


class TokenKind(str, Enum):
    """Token categories defined by the first native Ariadion grammar."""

    PROGRAM = "program"
    QUBITS = "qubits"
    X = "x"
    H = "h"
    Z = "z"
    RX = "rx"
    RY = "ry"
    RZ = "rz"
    CX = "cx"
    MEASURE = "measure"
    IDENTIFIER = "identifier"
    INTEGER_LITERAL = "integer_literal"
    ANGLE_LITERAL = "angle_literal"
    COMMA = ","
    LEFT_BRACKET = "["
    RIGHT_BRACKET = "]"
    ARROW = "->"
    NEWLINE = "newline"
    EOF = "eof"


@dataclass(frozen=True, slots=True)
class Token:
    """One source token with its original spelling and location."""

    kind: TokenKind
    spelling: str
    source_range: SourceRange

    def __post_init__(self) -> None:
        if not isinstance(self.kind, TokenKind):
            raise ValueError("token kind must be TokenKind")
        if not isinstance(self.spelling, str):
            raise ValueError("token spelling must be a string")
        if self.kind is TokenKind.EOF:
            if self.spelling:
                raise ValueError("EOF token spelling must be empty")
        elif not self.spelling:
            raise ValueError("source token spelling must be non-empty")
        if not isinstance(self.source_range, SourceRange):
            raise ValueError("token source_range must be SourceRange")
        if (
            self.source_range.line is None
            or self.source_range.column is None
            or self.source_range.end_line is None
            or self.source_range.end_column is None
        ):
            raise ValueError("token source_range must include a complete source span")

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "spelling": self.spelling,
            "source_range": self.source_range.to_dict(),
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())
