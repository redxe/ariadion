from __future__ import annotations

import inspect
from dataclasses import dataclass

from ariadion_ir import OperationId, SourceRange


@dataclass(frozen=True, slots=True)
class SourceOperation:
    name: str
    targets: tuple[int, ...]
    controls: tuple[int, ...] = ()
    key: str | None = None
    id: OperationId | None = None
    source_range: SourceRange | None = None

    def __post_init__(self) -> None:
        if self.id is not None and not self.id:
            raise ValueError("source operation ID must be non-empty")


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
        source_id: str | None = None,
    ) -> None:
        self.name = name
        self.qubit_count = qubit_count
        self.source_id = source_id if source_id is not None else f"program:{name}"
        if not self.source_id:
            raise ValueError("program source_id must be non-empty")
        self._operations: list[SourceOperation] = []
        self._operation_ids: set[OperationId] = set()

    @property
    def operations(self) -> tuple[SourceOperation, ...]:
        return tuple(self._operations)

    def x(
        self,
        target: int,
        *,
        source_id: OperationId | None = None,
        source_range: SourceRange | None = None,
    ) -> Program:
        return self._append(
            "x",
            (target,),
            source_id=source_id,
            source_range=source_range or _capture_callsite(),
        )

    def h(
        self,
        target: int,
        *,
        source_id: OperationId | None = None,
        source_range: SourceRange | None = None,
    ) -> Program:
        return self._append(
            "h",
            (target,),
            source_id=source_id,
            source_range=source_range or _capture_callsite(),
        )

    def z(
        self,
        target: int,
        *,
        source_id: OperationId | None = None,
        source_range: SourceRange | None = None,
    ) -> Program:
        return self._append(
            "z",
            (target,),
            source_id=source_id,
            source_range=source_range or _capture_callsite(),
        )

    def cx(
        self,
        control: int,
        target: int,
        *,
        source_id: OperationId | None = None,
        source_range: SourceRange | None = None,
    ) -> Program:
        return self._append(
            "cx",
            (target,),
            controls=(control,),
            source_id=source_id,
            source_range=source_range or _capture_callsite(),
        )

    def measure(
        self,
        target: int,
        *,
        key: str | None = None,
        source_id: OperationId | None = None,
        source_range: SourceRange | None = None,
    ) -> Program:
        return self._append(
            "measure",
            (target,),
            key=key,
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
        source_id: OperationId | None = None,
        source_range: SourceRange | None = None,
    ) -> Program:
        operation_id = (
            source_id
            if source_id is not None
            else OperationId(f"{self.source_id}:operation:{len(self._operations)}")
        )
        if operation_id in self._operation_ids:
            raise ValueError(f"source operation ID must be unique: {operation_id}")
        self._operation_ids.add(operation_id)
        self._operations.append(
            SourceOperation(
                name,
                targets,
                controls,
                key,
                id=operation_id,
                source_range=source_range,
            )
        )
        return self


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
