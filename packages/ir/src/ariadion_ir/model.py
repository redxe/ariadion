from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class OpCode(str, Enum):
    X = "X"
    H = "H"
    Z = "Z"
    CX = "CX"
    MEASURE = "MEASURE"


@dataclass(frozen=True, slots=True)
class SourceRef:
    file: str | None = None
    line: int | None = None
    column: int | None = None


@dataclass(frozen=True, slots=True)
class Operation:
    opcode: OpCode
    targets: tuple[int, ...]
    controls: tuple[int, ...] = ()
    key: str | None = None
    source: SourceRef | None = None


@dataclass(frozen=True, slots=True)
class CircuitIR:
    name: str
    qubit_count: int
    operations: tuple[Operation, ...]

    def operation_count(self) -> int:
        return len(self.operations)
