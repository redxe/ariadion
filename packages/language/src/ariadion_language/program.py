from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SourceOperation:
    name: str
    targets: tuple[int, ...]
    controls: tuple[int, ...] = ()
    key: str | None = None


class Program:
    """Mutable source-level program builder.

    Semantic validation intentionally belongs to Daidalon so frontends can collect
    multiple diagnostics before rejecting a program.
    """

    def __init__(self, qubit_count: int, *, name: str = "program") -> None:
        self.name = name
        self.qubit_count = qubit_count
        self._operations: list[SourceOperation] = []

    @property
    def operations(self) -> tuple[SourceOperation, ...]:
        return tuple(self._operations)

    def x(self, target: int) -> Program:
        return self._append("x", (target,))

    def h(self, target: int) -> Program:
        return self._append("h", (target,))

    def z(self, target: int) -> Program:
        return self._append("z", (target,))

    def cx(self, control: int, target: int) -> Program:
        return self._append("cx", (target,), controls=(control,))

    def measure(self, target: int, *, key: str | None = None) -> Program:
        return self._append("measure", (target,), key=key)

    def _append(
        self,
        name: str,
        targets: tuple[int, ...],
        *,
        controls: tuple[int, ...] = (),
        key: str | None = None,
    ) -> Program:
        self._operations.append(SourceOperation(name, targets, controls, key))
        return self
