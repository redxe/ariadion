"""Explicit capability wrappers for Ariadion's transparent reference engines."""

from __future__ import annotations

from typing import Final

from ariadion_ir import CircuitIR

from .backend import (
    SimulationCapabilities,
    SimulationPlan,
    SimulationQuery,
    StateRepresentation,
    build_simulation_plan,
)
from ariadion_noise import NoiseFeature
from .density_matrix import (
    DensityMatrixExecutionRequest,
    DensityMatrixResult,
    simulate_density_matrix,
)
from .statevector import (
    SampledExecutionRequest,
    SampledSimulationResult,
    SimulationResult,
    simulate,
)

_REFERENCE_STATE_VECTOR_CAPABILITIES: Final = SimulationCapabilities(
    representations=(StateRepresentation.STATE_VECTOR,),
    queries=(SimulationQuery.FULL_STATE, SimulationQuery.PROBABILITIES),
    noise_features=(),
    supports_reset=False,
    supports_sampling=False,
)
_REFERENCE_SAMPLED_TRAJECTORY_CAPABILITIES: Final = SimulationCapabilities(
    representations=(StateRepresentation.STATE_VECTOR,),
    queries=(SimulationQuery.FULL_STATE, SimulationQuery.SAMPLES),
    noise_features=(),
    supports_reset=True,
    supports_sampling=True,
)
_REFERENCE_DENSITY_MATRIX_CAPABILITIES: Final = SimulationCapabilities(
    representations=(StateRepresentation.DENSITY_MATRIX,),
    queries=(SimulationQuery.FULL_STATE, SimulationQuery.PROBABILITIES),
    noise_features=(NoiseFeature.GATE_CHANNELS, NoiseFeature.IDLE_DECOHERENCE),
    supports_reset=True,
    supports_sampling=False,
)


class ReferenceStateVectorBackend:
    """Transparent exact state-vector reference execution."""

    backend_id: Final = "reference-state-vector"
    representation: Final = StateRepresentation.STATE_VECTOR
    capabilities: Final = _REFERENCE_STATE_VECTOR_CAPABILITIES

    def plan(
        self,
        circuit: CircuitIR,
        *,
        query: SimulationQuery = SimulationQuery.FULL_STATE,
    ) -> SimulationPlan:
        return build_simulation_plan(
            backend_id=self.backend_id,
            capabilities=self.capabilities,
            representation=self.representation,
            query=query,
            reasons=(
                "caller explicitly selected the reference state-vector backend",
                "reference execution uses immutable Python complex tuples",
            ),
        )

    def execute(
        self,
        circuit: CircuitIR,
        *,
        options: None = None,
        query: SimulationQuery = SimulationQuery.FULL_STATE,
    ) -> SimulationResult:
        if options is not None:
            raise ValueError("reference-state-vector does not accept execution options")
        self.plan(circuit, query=query)
        return simulate(circuit)


class ReferenceSampledTrajectoryBackend:
    """Transparent seeded sampled state-vector trajectory execution."""

    backend_id: Final = "reference-sampled-trajectory"
    representation: Final = StateRepresentation.STATE_VECTOR
    capabilities: Final = _REFERENCE_SAMPLED_TRAJECTORY_CAPABILITIES

    def plan(
        self,
        circuit: CircuitIR,
        *,
        query: SimulationQuery = SimulationQuery.FULL_STATE,
    ) -> SimulationPlan:
        return build_simulation_plan(
            backend_id=self.backend_id,
            capabilities=self.capabilities,
            representation=self.representation,
            query=query,
            reasons=(
                "caller explicitly selected the reference sampled trajectory backend",
                "one independently initialized Python trajectory runs per requested shot",
            ),
        )

    def execute(
        self,
        circuit: CircuitIR,
        *,
        options: SampledExecutionRequest | None = None,
        query: SimulationQuery = SimulationQuery.FULL_STATE,
    ) -> SampledSimulationResult:
        if options is None:
            raise ValueError(
                "reference-sampled-trajectory requires SampledExecutionRequest options"
            )
        self.plan(circuit, query=query)
        result = simulate(circuit, execution=options)
        if not isinstance(result, SampledSimulationResult):  # pragma: no cover
            raise RuntimeError("sampled reference execution did not return sampled trajectories")
        return result


class ReferenceDensityMatrixBackend:
    """Transparent exact density-matrix reference execution."""

    backend_id: Final = "reference-density-matrix"
    representation: Final = StateRepresentation.DENSITY_MATRIX
    capabilities: Final = _REFERENCE_DENSITY_MATRIX_CAPABILITIES

    def plan(
        self,
        circuit: CircuitIR,
        *,
        query: SimulationQuery = SimulationQuery.FULL_STATE,
    ) -> SimulationPlan:
        return build_simulation_plan(
            backend_id=self.backend_id,
            capabilities=self.capabilities,
            representation=self.representation,
            query=query,
            reasons=(
                "caller explicitly selected the reference density-matrix backend",
                "reference execution uses immutable Python density-matrix tuples",
            ),
        )

    def execute(
        self,
        circuit: CircuitIR,
        *,
        options: DensityMatrixExecutionRequest | None = None,
        query: SimulationQuery = SimulationQuery.FULL_STATE,
    ) -> DensityMatrixResult:
        self.plan(circuit, query=query)
        return simulate_density_matrix(circuit, execution=options)


__all__ = [
    "ReferenceDensityMatrixBackend",
    "ReferenceSampledTrajectoryBackend",
    "ReferenceStateVectorBackend",
]
