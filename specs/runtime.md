# Runtime execution trace contract — draft 0

`ariadion-runtime` defines the versioned, frontend-neutral contract for an
operation-by-operation execution trace. This document defines data only; the
reference simulator does not produce traces until the trace-producing simulation
issue is implemented.

## Capture boundary

`TraceCaptureOptions(enabled=False)` is the producer-facing opt-in. A producer
with capture disabled returns no `ExecutionTrace` and must not retain intermediate
state vectors. With capture enabled, it returns one `ExecutionTrace` for the
executed circuit.

## Identity and indexing

An `ExecutionTrace` is scoped by `circuit_id`, which equals `CircuitIR.id`. Each
`TraceStep` owns an immutable IR `Operation`, exposing its `IrOperationId`, source
reference, and compiler provenance. Consumers should key a step by the pair
`(circuit_id, ir_operation_id)` and use its `SourceNodeId` only for persisted
editor identity. `IrOperationId` values are unique within a trace. Future control
flow that executes one semantic IR operation more than once must introduce a
separate execution-occurrence identity.

`initial_state` represents the state before any operation. `TraceStep.index` is
zero-based and identifies the corresponding executed operation. A trace with an
empty circuit therefore has an initial state and zero steps; a one-operation trace
has one step at index zero. Every step records `before` and `after` snapshots, and
the next step must begin with the preceding step's `after` snapshot.

## Exact state and sampled measurements

`StateSnapshot` currently supports the explicit `state_vector` representation.
Its amplitudes are exact simulation data, not sampled counts. The representation
field reserves room for future density-matrix and reduced-state contracts.
Every amplitude component must be finite; `NaN` and infinities are invalid.

`ExecutionMetadata.mode` labels a complete trace as `exact` or `sampled`.
`MeasurementEvent` makes exact probabilities and sampled outcomes mutually
exclusive: an `exact_probabilities` record contains probability data, while a
`sampled_outcome` record contains one bit per measured target. Exact traces reject
sampled outcomes by invariant. A measurement event can attach only to a `MEASURE`
operation with the same operation ID, targets, and key. Targets must be unique and
fit the snapshot width. Exact records have exactly $2^n$ finite, non-negative
probabilities for $n$ targets, and those probabilities must sum to one within an
absolute tolerance of $10^{-12}$.

## Immutability and metadata

All contract objects are frozen dataclasses with tuple-backed collections. Public
snapshots reject mutable amplitude lists, so consumers cannot observe simulator
internals changing after a trace is captured. Optional `ExecutionMetadata` and
`ResourceMetric` records carry execution mode, seed, timing, and resource values
without requiring a specific simulator or provider implementation.

## Serialization and versioning

`ExecutionTrace` starts at `schema_version = 1`. All contract records provide
`to_dict()` and canonical `to_json()` output. Consumers must reject unsupported
future schema versions rather than guessing their meaning. Additive optional fields
are preferred for compatible evolution; semantic changes require a new schema
version. Canonical JSON is strict: it never emits `NaN` or infinity values.
