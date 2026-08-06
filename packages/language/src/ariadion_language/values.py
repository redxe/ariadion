from __future__ import annotations

from dataclasses import dataclass
from itertools import count
from threading import Lock
from typing import Self

from ariadion_core import LogicalQubitId, canonical_json, require_nonempty_identifier


_LOGICAL_QUBIT_COUNTER = count()
_LOGICAL_QUBIT_LOCK = Lock()


@dataclass(frozen=True, slots=True, init=False, repr=False)
class Qubit:
    """A public logical quantum value with no allocated physical location."""

    _logical_id: LogicalQubitId

    def __init__(self) -> None:
        object.__setattr__(self, "_logical_id", _next_logical_qubit_id())

    @classmethod
    def _from_logical_id(cls, logical_id: LogicalQubitId) -> Self:
        """Create a value with an injected semantic identity for internal frontends."""

        require_nonempty_identifier(logical_id, label="logical qubit ID")
        value = object.__new__(cls)
        object.__setattr__(value, "_logical_id", logical_id)
        return value

    def __bool__(self) -> bool:
        raise TypeError(
            "Qubit cannot be used as a Boolean; observe it explicitly or return it "
            "through a declared classical boundary"
        )

    def __copy__(self) -> Self:
        return self

    def __deepcopy__(self, memo: dict[int, object]) -> Self:
        memo[id(self)] = self
        return self

    def __repr__(self) -> str:
        return "Qubit()"


@dataclass(frozen=True, slots=True)
class Bit:
    """A classical observation result, distinct from a quantum value and ``bool``."""

    value: bool

    def __post_init__(self) -> None:
        if not isinstance(self.value, bool):
            raise ValueError("bit value must be bool")

    def __bool__(self) -> bool:
        return self.value

    def to_dict(self) -> dict[str, bool]:
        return {"value": self.value}

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


def _next_logical_qubit_id() -> LogicalQubitId:
    with _LOGICAL_QUBIT_LOCK:
        return LogicalQubitId(f"logical-qubit:{next(_LOGICAL_QUBIT_COUNTER)}")
