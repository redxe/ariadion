from __future__ import annotations

from dataclasses import dataclass
from typing import Never

from ariadion_core import require_nonempty_identifier


@dataclass(frozen=True, slots=True)
class QuantumIntrinsic:
    """A stable, non-executing marker resolved by the Python AST frontend."""

    name: str

    def __post_init__(self) -> None:
        require_nonempty_identifier(self.name, label="quantum intrinsic name")

    def __call__(self, *args: object, **kwargs: object) -> Never:
        del args, kwargs
        raise RuntimeError(
            f"Ariadion quantum intrinsic `{self.name}` cannot execute as ordinary Python. "
            "Use it inside an @quantum function."
        )


h = QuantumIntrinsic("h")
x = QuantumIntrinsic("x")
z = QuantumIntrinsic("z")
cx = QuantumIntrinsic("cx")
rx = QuantumIntrinsic("rx")
ry = QuantumIntrinsic("ry")
rz = QuantumIntrinsic("rz")
observe = QuantumIntrinsic("observe")
reset = QuantumIntrinsic("reset")
