from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass

from .identity import (
    ProgramId,
    SnapshotOperationId,
    SourceIdentity,
    SourceNodeId,
    require_nonempty_identifier,
)


def canonical_json(value: Mapping[str, object]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


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
        return canonical_json(self.to_dict())



@dataclass(frozen=True, slots=True)
class SourceRef:
    """A source reference scoped to one program snapshot."""

    program_id: ProgramId
    snapshot_operation_id: SnapshotOperationId
    file: str | None = None
    line: int | None = None
    column: int | None = None
    end_line: int | None = None
    end_column: int | None = None
    source_node_id: SourceNodeId | None = None

    def __post_init__(self) -> None:
        require_nonempty_identifier(self.program_id, label="program ID")
        require_nonempty_identifier(
            self.snapshot_operation_id,
            label="snapshot operation ID",
        )
        if self.source_node_id is not None:
            require_nonempty_identifier(self.source_node_id, label="source node ID")
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
        *,
        program_id: ProgramId,
        snapshot_operation_id: SnapshotOperationId,
        source_range: SourceRange | None,
        source_node_id: SourceNodeId | None = None,
    ) -> SourceRef:
        if source_range is None:
            return cls(
                program_id=program_id,
                snapshot_operation_id=snapshot_operation_id,
                source_node_id=source_node_id,
            )
        return cls(
            program_id=program_id,
            snapshot_operation_id=snapshot_operation_id,
            file=source_range.file,
            line=source_range.line,
            column=source_range.column,
            end_line=source_range.end_line,
            end_column=source_range.end_column,
            source_node_id=source_node_id,
        )

    @property
    def source_id(self) -> SourceIdentity:
        """Compatibility view; prefer explicit snapshot or durable node IDs."""
        return self.source_node_id or self.snapshot_operation_id

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
            "program_id": self.program_id,
            "snapshot_operation_id": self.snapshot_operation_id,
            "source_node_id": self.source_node_id,
            "file": self.file,
            "line": self.line,
            "column": self.column,
            "end_line": self.end_line,
            "end_column": self.end_column,
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())