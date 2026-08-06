from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field as dataclass_field

from .identity import (
    ProgramId,
    SnapshotOperationId,
    SourceIdentity,
    SourceNodeId,
    SourceOperationId,
    require_nonempty_identifier,
)


def canonical_json(value: Mapping[str, object]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


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



@dataclass(frozen=True, slots=True, init=False)
class SourceRef:
    """A neutral source reference scoped to one program or document.

    ``source_operation_id`` is the canonical identity for the source construct.
    ``snapshot_operation_id`` remains available only for references created by the
    compatibility width-based builder; semantic programs never need to invent one.
    """

    program_id: ProgramId
    source_operation_id: SourceOperationId
    file: str | None = None
    line: int | None = None
    column: int | None = None
    end_line: int | None = None
    end_column: int | None = None
    source_node_id: SourceNodeId | None = None
    _snapshot_operation_id: SnapshotOperationId | None = dataclass_field(repr=False, compare=False)

    def __init__(
        self,
        program_id: ProgramId,
        snapshot_operation_id: SnapshotOperationId | None = None,
        file: str | None = None,
        line: int | None = None,
        column: int | None = None,
        end_line: int | None = None,
        end_column: int | None = None,
        source_node_id: SourceNodeId | None = None,
        *,
        source_operation_id: SourceOperationId | None = None,
    ) -> None:
        resolved_source_operation_id = _resolve_source_operation_id(
            source_operation_id=source_operation_id,
            snapshot_operation_id=snapshot_operation_id,
        )
        object.__setattr__(self, "program_id", program_id)
        object.__setattr__(self, "source_operation_id", resolved_source_operation_id)
        object.__setattr__(self, "file", file)
        object.__setattr__(self, "line", line)
        object.__setattr__(self, "column", column)
        object.__setattr__(self, "end_line", end_line)
        object.__setattr__(self, "end_column", end_column)
        object.__setattr__(self, "source_node_id", source_node_id)
        object.__setattr__(self, "_snapshot_operation_id", snapshot_operation_id)
        self.__post_init__()

    def __post_init__(self) -> None:
        require_nonempty_identifier(self.program_id, label="program ID")
        require_nonempty_identifier(
            self.source_operation_id,
            label="source operation ID",
        )
        if self._snapshot_operation_id is not None:
            require_nonempty_identifier(
                self._snapshot_operation_id,
                label="snapshot operation ID",
            )
            if self.source_operation_id != SourceOperationId(self._snapshot_operation_id):
                raise ValueError(
                    "snapshot operation ID must match source operation ID when provided"
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
        source_range: SourceRange | None,
        source_operation_id: SourceOperationId | None = None,
        snapshot_operation_id: SnapshotOperationId | None = None,
        source_node_id: SourceNodeId | None = None,
    ) -> SourceRef:
        resolved_source_operation_id = _resolve_source_operation_id(
            source_operation_id=source_operation_id,
            snapshot_operation_id=snapshot_operation_id,
        )
        if source_range is None:
            return cls(
                program_id=program_id,
                source_operation_id=resolved_source_operation_id,
                source_node_id=source_node_id,
                snapshot_operation_id=snapshot_operation_id,
            )
        return cls(
            program_id=program_id,
            source_operation_id=resolved_source_operation_id,
            file=source_range.file,
            line=source_range.line,
            column=source_range.column,
            end_line=source_range.end_line,
            end_column=source_range.end_column,
            source_node_id=source_node_id,
            snapshot_operation_id=snapshot_operation_id,
        )

    @property
    def source_id(self) -> SourceIdentity:
        """Prefer the durable node identity, then the neutral source identity."""
        return self.source_node_id or self.source_operation_id

    @property
    def snapshot_operation_id(self) -> SnapshotOperationId | None:
        """Compatibility identity for builder-derived references, when available."""
        return self._snapshot_operation_id

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
            "source_operation_id": self.source_operation_id,
            "source_node_id": self.source_node_id,
            "file": self.file,
            "line": self.line,
            "column": self.column,
            "end_line": self.end_line,
            "end_column": self.end_column,
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


def _resolve_source_operation_id(
    *,
    source_operation_id: SourceOperationId | None,
    snapshot_operation_id: SnapshotOperationId | None,
) -> SourceOperationId:
    if source_operation_id is None:
        if snapshot_operation_id is None:
            raise ValueError("source operation ID is required")
        return SourceOperationId(snapshot_operation_id)
    if (
        snapshot_operation_id is not None
        and source_operation_id != SourceOperationId(snapshot_operation_id)
    ):
        raise ValueError("snapshot operation ID must match source operation ID when provided")
    return source_operation_id
