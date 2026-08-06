# Theonoe trace inspection contract — draft 0

Theonoe inspects immutable state vectors and state transitions. It does not mutate
an `ExecutionTrace`, simulate operations, or decide execution policy. Runtime
exposes `inspect_execution_trace()` as an explicit projection from a captured
execution trace into a `TraceInspection`.

## State reports

`StateReport` represents one exact state-vector snapshot. It contains visible
basis states with amplitude, probability, and principal phase, filtered by the
configured probability epsilon (default $10^{-12}$). Full state vectors remain in
the execution trace; filtering exists only for inspection display data.

Theonoe accepts normalized pure state vectors only. Every public amplitude input
must have norm one within `STATE_VECTOR_NORM_ABS_TOLERANCE` (default $10^{-12}$).
Invalid vectors are rejected; inspection never silently normalizes them.

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
are visible. Theonoe canonicalizes each snapshot's global phase before comparing
basis states, so global-phase-equivalent vectors do not produce basis changes. If
the snapshots are physically equivalent, `global_phase_delta_radians` records the
otherwise unobservable phase delta. An `EntanglementTransition` records newly
entangled, newly separable, persistent entangled, and persistent separable qubits.

The runtime-owned `TraceStepInspection` binds this analysis to the immutable IR
operation identity, source reference, optional lowered observation metadata,
optional measurement data, and step index. `TraceInspection` contains the initial
report plus every step inspection. For an exact terminal observation, its before and
after reports describe the retained analytical state; they are not a physical
post-measurement state report. Per-observation exact probabilities in this data are
`marginal` facts about one measurement's targets, never a substitute for the
logical run's separately calculated `joint_return` classical distribution.

## Rotation explanations

For `RX`, `RY`, and `RZ` trace steps, runtime asks Theonoe to explain the exact
`StateTransition` using primitive operation facts: rotation axis, target, canonical
radians, and optional source-unit angle. Theonoe does not import runtime contracts
or simulate operations.

`RotationExplanation` separates `exact_claims` from one
`educational_interpretation`. Exact claims describe only the inspected transition:
computational-basis probability changes, detected relative-phase changes, an
unobservable global-phase delta when applicable, and the exact diagonal property
of `RZ`. The educational interpretation provides careful Bloch-sphere and
interference context; it is not a replacement for the exact state-vector facts.
`RotationEffect` classifies the observed effect as probability-changing,
relative-phase-only, global-phase-only, or no visible change.

## Serialization

All inspection records are frozen dataclasses with `to_dict()` and canonical
`to_json()` output. Complex values are serialized as real/imaginary component
objects. `TraceInspection.inspection_schema_version` independently versions the
inspection payload, while `TraceInspection.trace_schema_version` preserves the
associated schema-v3 `ExecutionTrace.schema_version` when storing or exchanging an
inspection. `rotation_explanation` is an additive optional step field. The initial
`INSPECTION_SCHEMA_VERSION` is $1$.
