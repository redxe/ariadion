# Theonoe trace inspection contract — draft 0

Theonoe inspects immutable state vectors and state transitions. It does not mutate
an `ExecutionTrace`, simulate operations, or decide execution policy. Runtime
projects a captured execution trace into a `TraceInspection` only after simulation
has completed.

## State reports

`StateReport` represents one exact state-vector snapshot. It contains visible
basis states with amplitude, probability, and principal phase, filtered by the
configured probability epsilon (default $10^{-12}$). Full state vectors remain in
the execution trace; filtering exists only for inspection display data.

Each report also contains one `ReducedDensityMatrix` per qubit. A reduced matrix
includes all $2 \times 2$ complex matrix elements, purity, and whether the qubit
is separable from the rest of the pure global state within the separability
tolerance (default $10^{-9}$).

## Separability and groups

A report is `proven_fully_separable` when every one-qubit reduced state is pure
within tolerance. This proves full product-state separability for the represented
pure state vector.

`heuristic_subsystems` is intentionally not a proof of multipartite structure.
It places individually separable qubits in singleton groups and groups all qubits
with mixed one-qubit reductions together. This makes likely correlated regions
visible without claiming that a grouping distinguishes Bell pairs, GHZ states, or
other multipartite structures. Future analyses may add certified bipartition
factorization and entanglement witnesses.

## State transitions

`StateTransition` contains a before and after `StateReport`, basis-state changes,
and an `EntanglementTransition`. Every basis change records amplitudes,
probabilities, probability delta, and a relative phase delta when both amplitudes
are visible. An `EntanglementTransition` records newly entangled, newly separable,
persistent entangled, and persistent separable qubits.

The runtime-owned `TraceStepInspection` binds this analysis to the immutable IR
operation identity, source reference, optional measurement data, and step index.
`TraceInspection` contains the initial report plus every step inspection.

## Serialization

All inspection records are frozen dataclasses with `to_dict()` and canonical
`to_json()` output. Complex values are serialized as real/imaginary component
objects. `TraceInspection.trace_schema_version` preserves the associated
`ExecutionTrace.schema_version` when storing or exchanging an inspection.
