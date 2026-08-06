from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from itertools import count

from ariadion_core import (
    ProgramId,
    SnapshotOperationId,
    SourceNodeId,
    SourceRange,
    require_nonempty_identifier,
)


_PROGRAM_COUNTER = count()


@dataclass(frozen=True, slots=True)
class SourceOperation:
    name: str
    targets: tuple[int, ...]
    controls: tuple[int, ...] = ()
    key: str | None = None
    id: SnapshotOperationId = field(kw_only=True)
    source_node_id: SourceNodeId | None = None
    source_range: SourceRange | None = None

    def __post_init__(self) -> None:
        require_nonempty_identifier(self.id, label="snapshot operation ID")
        if self.source_node_id is not None:
            require_nonempty_identifier(self.source_node_id, label="source node ID")


class Program:
    """Mutable source-level program builder.

    Semantic validation intentionally belongs to Daidalon so frontends can collect
    multiple diagnostics before rejecting a program.
    """

    def __init__(
        self,
        qubit_count: int,
        *,
        name: str = "program",
        program_id: ProgramId | None = None,
        source_id: ProgramId | None = None,
    ) -> None:
        if program_id is not None and source_id is not None:
            raise ValueError("program_id and source_id cannot both be provided")
        self.name = name
        self.qubit_count = qubit_count
        requested_program_id = program_id if program_id is not None else source_id
        self.id = (
            requested_program_id
            if requested_program_id is not None
            else _default_program_id(name)
        )
        require_nonempty_identifier(self.id, label="program ID")
        # Compatibility alias for callers of the original source-identity API.
        self.source_id = self.id
        self._operations: list[SourceOperation] = []
        self._operation_ids: set[SnapshotOperationId] = set()

    @property
    def operations(self) -> tuple[SourceOperation, ...]:
        return tuple(self._operations)

    def x(
        self,
        target: int,
        *,
        source_node_id: SourceNodeId | None = None,
        source_id: SourceNodeId | None = None,
        source_range: SourceRange | None = None,
    ) -> Program:
        return self._append(
            "x",
            (target,),
            source_node_id=source_node_id,
            source_id=source_id,
            source_range=source_range or _capture_callsite(),
        )

    def h(
        self,
        target: int,
        *,
        source_node_id: SourceNodeId | None = None,
        source_id: SourceNodeId | None = None,
        source_range: SourceRange | None = None,
    ) -> Program:
        return self._append(
            "h",
            (target,),
            source_node_id=source_node_id,
            source_id=source_id,
            source_range=source_range or _capture_callsite(),
        )

    def z(
        self,
        target: int,
        *,
        source_node_id: SourceNodeId | None = None,
        source_id: SourceNodeId | None = None,
        source_range: SourceRange | None = None,
    ) -> Program:
        return self._append(
            "z",
            (target,),
            source_node_id=source_node_id,
            source_id=source_id,
            source_range=source_range or _capture_callsite(),
        )

    def cx(
        self,
        control: int,
        target: int,
        *,
        source_node_id: SourceNodeId | None = None,
        source_id: SourceNodeId | None = None,
        source_range: SourceRange | None = None,
    ) -> Program:
        return self._append(
            "cx",
            (target,),
            controls=(control,),
            source_node_id=source_node_id,
            source_id=source_id,
            source_range=source_range or _capture_callsite(),
        )

    def measure(
        self,
        target: int,
        *,
        key: str | None = None,
        source_node_id: SourceNodeId | None = None,
        source_id: SourceNodeId | None = None,
        source_range: SourceRange | None = None,
    ) -> Program:
        return self._append(
            "measure",
            (target,),
            key=key,
            source_node_id=source_node_id,
            source_id=source_id,
            source_range=source_range or _capture_callsite(),
        )

    def _append(
        self,
        name: str,
        targets: tuple[int, ...],
        *,
        controls: tuple[int, ...] = (),
        key: str | None = None,
        source_node_id: SourceNodeId | None = None,
        source_id: SourceNodeId | None = None,
        source_range: SourceRange | None = None,
    ) -> Program:
        durable_node_id = _resolve_source_node_id(source_node_id, source_id)
        operation = SourceOperation(
            name,
            targets,
            controls,
            key,
            id=SnapshotOperationId(f"{self.id}:operation:{len(self._operations)}"),
            source_node_id=durable_node_id,
            source_range=source_range,
        )
        if operation.id in self._operation_ids:
            raise ValueError(f"snapshot operation ID must be unique: {operation.id}")
        self._operations.append(operation)
        self._operation_ids.add(operation.id)
        return self


def _default_program_id(name: str) -> ProgramId:
    return ProgramId(f"snapshot:{next(_PROGRAM_COUNTER)}:{name}")


def _resolve_source_node_id(
    source_node_id: SourceNodeId | None,
    source_id: SourceNodeId | None,
) -> SourceNodeId | None:
    if source_node_id is not None and source_id is not None:
        raise ValueError("source_node_id and source_id cannot both be provided")
    return source_node_id if source_node_id is not None else source_id


def _capture_callsite() -> SourceRange | None:
    frame = inspect.currentframe()
    try:
        if frame is None:
            return None
        public_method = frame.f_back
        if public_method is None:
            return None
        caller = public_method.f_back
        if caller is None:
            return None
        return SourceRange(file=caller.f_code.co_filename, line=caller.f_lineno)
    finally:
        del frame
