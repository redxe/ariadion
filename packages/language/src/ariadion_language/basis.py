from __future__ import annotations

from dataclasses import dataclass

from ariadion_core import canonical_json, require_nonempty_identifier


@dataclass(frozen=True, slots=True)
class Basis:
    """A public basis descriptor whose name may later bind to a custom basis."""

    name: str

    def __post_init__(self) -> None:
        require_nonempty_identifier(self.name, label="basis name")

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name}

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class BasisNamespace:
    """Immutable public basis namespace kept distinct from gate-function names."""

    @property
    def x(self) -> Basis:
        return Basis("x")

    @property
    def y(self) -> Basis:
        return Basis("y")

    @property
    def z(self) -> Basis:
        return Basis("z")

    def named(self, name: str) -> Basis:
        return Basis(name)


basis = BasisNamespace()
