from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import NewType


OperationId = NewType("OperationId", str)


def _canonical_json(value: Mapping[str, object]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


class OpCode(str, Enum):
    X = "X"
    H = "H"
    Z = "Z"
    CX = "CX"
    MEASURE = "MEASURE"


@dataclass(frozen=True, slots=True)
class SourceRange:
    file: str | None = None
    line: int | None = None
    column: int | None = None
    end_line: int | None = None
    end_column: int | None = None

    def __post_init__(self) -> None:
        positions = {
            "line": self.line,
            "column": self.column,
            "end_line": self.end_line,
            "end_column": self.end_column,
        }
        for name, value in positions.items():
            if value is not None and value < 1:
                raise ValueError(f"source {name} must be one-based when provided")

        if self.line is None and any(
            value is not None for value in (self.column, self.end_line, self.end_column)
        ):
            raise ValueError("source line is required when source positions are provided")
        if self.end_line is None and self.end_column is not None:
            raise ValueError("source end_line is required when end_column is provided")
        if self.line is not None and self.end_line is not None:
            if self.end_line < self.line:
                raise ValueError("source end_line cannot precede source line")
            if (
                self.end_line == self.line
                and self.column is not None
                and self.end_column is not None
                and self.end_column < self.column
            ):
                raise ValueError("source end_column cannot precede source column")

    def to_dict(self) -> dict[str, str | int | None]:
        return {
            "file": self.file,
            "line": self.line,
            "column": self.column,
            "end_line": self.end_line,
            "end_column": self.end_column,
        }

    def to_json(self) -> str:
        return _canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class SourceRef:
    """A stable source-operation ID paired with an optional source range."""

    file: str | None = None
    line: int | None = None
    column: int | None = None
    end_line: int | None = None
    end_column: int | None = None
    source_id: OperationId | None = None

    def __post_init__(self) -> None:
        SourceRange(
            file=self.file,
            line=self.line,
            column=self.column,
            end_line=self.end_line,
            end_column=self.end_column,
        )

    @classmethod
    def from_range(
        cls,
        source_id: OperationId,
        source_range: SourceRange | None,
    ) -> SourceRef:
        if source_range is None:
            return cls(source_id=source_id)
        return cls(
            file=source_range.file,
            line=source_range.line,
            column=source_range.column,
            end_line=source_range.end_line,
            end_column=source_range.end_column,
            source_id=source_id,
        )

    @property
    def source_range(self) -> SourceRange | None:
        if not any(
            value is not None
            for value in (self.file, self.line, self.column, self.end_line, self.end_column)
        ):
            return None
        return SourceRange(
            file=self.file,
            line=self.line,
            column=self.column,
            end_line=self.end_line,
            end_column=self.end_column,
        )

    def to_dict(self) -> dict[str, str | int | None]:
        return {
            "source_id": self.source_id,
            "file": self.file,
            "line": self.line,
            "column": self.column,
            "end_line": self.end_line,
            "end_column": self.end_column,
        }

    def to_json(self) -> str:
        return _canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class OperationProvenance:
    """Describes source operations and transformations behind generated IR."""

    parent_source_ids: tuple[OperationId, ...] = ()
    transformation: str | None = None

    def __post_init__(self) -> None:
        if any(not source_id for source_id in self.parent_source_ids):
            raise ValueError("provenance parent source IDs must be non-empty")

    def to_dict(self) -> dict[str, object]:
        return {
            "parent_source_ids": list(self.parent_source_ids),
            "transformation": self.transformation,
        }

    def to_json(self) -> str:
        return _canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class Operation:
    opcode: OpCode
    targets: tuple[int, ...]
    controls: tuple[int, ...] = ()
    key: str | None = None
    source: SourceRef | None = None
    provenance: OperationProvenance | None = None

    @property
    def source_id(self) -> OperationId | None:
        return self.source.source_id if self.source is not None else None

    @property
    def source_range(self) -> SourceRange | None:
        return self.source.source_range if self.source is not None else None


@dataclass(frozen=True, slots=True)
class CircuitIR:
    name: str
    qubit_count: int
    operations: tuple[Operation, ...]

    def operation_count(self) -> int:
        return len(self.operations)
