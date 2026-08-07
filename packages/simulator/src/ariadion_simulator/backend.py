"""Framework-neutral simulation backend capability and planning contracts.

Ariadion keeps quantum semantics and execution planning separate from numerical
realizations. This module intentionally exposes only immutable Python values; it
does not expose arrays, device buffers, or a particular acceleration framework.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Generic, Protocol, TypeVar, runtime_checkable

from ariadion_core import canonical_json, require_nonempty_identifier
from ariadion_ir import CircuitIR


class StateRepresentation(str, Enum):
    """A complete state representation a backend can realize.

    This is an execution-capability enum. It is intentionally separate from the
    amplitude-only ``ariadion_runtime.trace.StateRepresentation`` schema.
    """

    STATE_VECTOR = "state_vector"
    DENSITY_MATRIX = "density_matrix"
    STABILIZER = "stabilizer"
    TENSOR_NETWORK = "tensor_network"


class SimulationQuery(str, Enum):
    """A semantic result shape that a backend can answer."""

    FULL_STATE = "full_state"
    PROBABILITIES = "probabilities"
    SAMPLES = "samples"
    OBSERVABLES = "observables"
    REDUCED_STATE = "reduced_state"


_REPRESENTATION_ORDER = {
    representation: index for index, representation in enumerate(StateRepresentation)
}
_QUERY_ORDER = {query: index for index, query in enumerate(SimulationQuery)}


@dataclass(frozen=True, slots=True)
class SimulationCapabilities:
    """Declared backend support without exposing numerical implementation details."""

    representations: tuple[StateRepresentation, ...]
    queries: tuple[SimulationQuery, ...]
    supports_noise: bool
    supports_reset: bool
    supports_sampling: bool

    def __post_init__(self) -> None:
        if not isinstance(self.representations, tuple) or not self.representations:
            raise ValueError("simulation capabilities representations must be a non-empty tuple")
        if not all(
            isinstance(representation, StateRepresentation)
            for representation in self.representations
        ):
            raise ValueError(
                "simulation capabilities representations must contain StateRepresentation values"
            )
        if len(self.representations) != len(set(self.representations)):
            raise ValueError("simulation capabilities representations must be unique")
        if not isinstance(self.queries, tuple) or not self.queries:
            raise ValueError("simulation capabilities queries must be a non-empty tuple")
        if not all(isinstance(query, SimulationQuery) for query in self.queries):
            raise ValueError("simulation capabilities queries must contain SimulationQuery values")
        if len(self.queries) != len(set(self.queries)):
            raise ValueError("simulation capabilities queries must be unique")
        for value, label in (
            (self.supports_noise, "supports_noise"),
            (self.supports_reset, "supports_reset"),
            (self.supports_sampling, "supports_sampling"),
        ):
            if not isinstance(value, bool):
                raise ValueError(f"simulation capabilities {label} must be a boolean")
        object.__setattr__(
            self,
            "representations",
            tuple(sorted(self.representations, key=_REPRESENTATION_ORDER.__getitem__)),
        )
        object.__setattr__(
            self,
            "queries",
            tuple(sorted(self.queries, key=_QUERY_ORDER.__getitem__)),
        )

    def supports(self, representation: StateRepresentation, query: SimulationQuery) -> bool:
        """Return whether this backend supports the requested semantic work."""

        return representation in self.representations and query in self.queries

    def to_dict(self) -> dict[str, object]:
        return {
            "representations": [representation.value for representation in self.representations],
            "queries": [query.value for query in self.queries],
            "supports_noise": self.supports_noise,
            "supports_reset": self.supports_reset,
            "supports_sampling": self.supports_sampling,
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class SimulationPlan:
    """Inspectable evidence for explicit backend selection.

    The plan records an already selected implementation. It deliberately does not
    make an automatic policy decision from circuit size, memory, hardware, or
    numerical cost; later planners can add those reasons without changing this
    contract.
    """

    backend_id: str
    representation: StateRepresentation
    query: SimulationQuery
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_nonempty_identifier(self.backend_id, label="simulation plan backend ID")
        if not isinstance(self.representation, StateRepresentation):
            raise ValueError("simulation plan representation must be StateRepresentation")
        if not isinstance(self.query, SimulationQuery):
            raise ValueError("simulation plan query must be SimulationQuery")
        if not isinstance(self.reasons, tuple) or not self.reasons:
            raise ValueError("simulation plan reasons must be a non-empty tuple")
        for reason in self.reasons:
            require_nonempty_identifier(reason, label="simulation plan reason")

    def to_dict(self) -> dict[str, object]:
        return {
            "backend_id": self.backend_id,
            "representation": self.representation.value,
            "query": self.query.value,
            "reasons": list(self.reasons),
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


_BackendOptions = TypeVar("_BackendOptions", contravariant=True)
_BackendResult = TypeVar("_BackendResult", covariant=True)


@runtime_checkable
class SimulationBackend(Protocol[_BackendOptions, _BackendResult]):
    """A replaceable numerical realization of fixed Ariadion semantics."""

    backend_id: str
    representation: StateRepresentation
    capabilities: SimulationCapabilities

    def plan(
        self,
        circuit: CircuitIR,
        *,
        query: SimulationQuery = SimulationQuery.FULL_STATE,
    ) -> SimulationPlan:
        """Build evidence for this explicit backend choice."""

    def execute(
        self,
        circuit: CircuitIR,
        *,
        options: _BackendOptions | None = None,
        query: SimulationQuery = SimulationQuery.FULL_STATE,
    ) -> _BackendResult:
        """Execute one circuit without leaking implementation-specific buffers."""


@dataclass(frozen=True, slots=True)
class BackendExecution(Generic[_BackendResult]):
    """A backend result paired with its inspected explicit selection plan."""

    plan: SimulationPlan
    result: _BackendResult


def build_simulation_plan(
    *,
    backend_id: str,
    capabilities: SimulationCapabilities,
    representation: StateRepresentation,
    query: SimulationQuery,
    reasons: tuple[str, ...],
) -> SimulationPlan:
    """Validate one explicit choice against declared backend capabilities."""

    if not isinstance(capabilities, SimulationCapabilities):
        raise ValueError("simulation plan capabilities must be SimulationCapabilities")
    if not capabilities.supports(representation, query):
        raise ValueError(
            "simulation backend does not support the requested representation and query"
        )
    return SimulationPlan(
        backend_id=backend_id,
        representation=representation,
        query=query,
        reasons=reasons,
    )


def execute_with_backend(
    backend: SimulationBackend[_BackendOptions, _BackendResult],
    circuit: CircuitIR,
    *,
    options: _BackendOptions | None = None,
    query: SimulationQuery = SimulationQuery.FULL_STATE,
) -> BackendExecution[_BackendResult]:
    """Run a caller-selected backend and retain its selection evidence.

    This helper never chooses a backend. Callers provide an implementation
    explicitly, preserving the current runtime defaults as reference execution.
    """

    if not isinstance(circuit, CircuitIR):
        raise ValueError("backend execution circuit must be CircuitIR")
    return BackendExecution(
        plan=backend.plan(circuit, query=query),
        result=backend.execute(circuit, options=options, query=query),
    )


__all__ = [
    "BackendExecution",
    "SimulationBackend",
    "SimulationCapabilities",
    "SimulationPlan",
    "SimulationQuery",
    "StateRepresentation",
    "build_simulation_plan",
    "execute_with_backend",
]
