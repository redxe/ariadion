# Runtime execution trace contract — draft 0

`ariadion-runtime` defines the versioned, frontend-neutral contract for an
operation-by-operation execution trace. The reference state-vector simulator
captures immutable raw amplitude tuples; runtime adapts that capture to this
public contract without exposing simulator buffers.

## Capture boundary

`TraceCaptureOptions(enabled=False)` is the producer-facing opt-in. A producer
with capture disabled returns no `ExecutionTrace` and must not retain intermediate
state vectors. With capture enabled, it returns one `ExecutionTrace` for the
executed circuit. The reference simulator retains an initial state and one
before/after transition per current IR operation only while capture is enabled.
An exact trace describes one analytical execution. A sampled trace describes one
collapsed trajectory, not an aggregate of multiple shots. Consequently, enabled
sampled trace capture requires exactly one shot; a request for multiple shots is
rejected with `A204` rather than concatenating unrelated trajectories.

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
the next step must begin with the preceding step's `after` snapshot. For an exact
terminal observation, `after` is the retained analytical state rather than a
sampled physical post-measurement state. `ExecutionTrace.retained_analytic_state`
is the explicit name for that final analytical snapshot.

## Exact state and sampled measurements

`StateSnapshot` currently supports the explicit `state_vector` representation.
Its amplitudes are exact simulation data, not sampled counts. Density execution
uses a separate `DensityMatrixResult` instead of pretending its matrix is an
amplitude snapshot. Every amplitude component must be finite; `NaN` and infinities
are invalid.

`ExecutionMetadata.mode` labels a complete trace as `exact` or `sampled`.
`MeasurementEvent` makes exact probabilities and sampled outcomes mutually
exclusive: an `exact_probabilities` record contains probability data, while a
`sampled_outcome` record contains one bit per measured target. Its required
`execution_kind` makes the semantic boundary explicit:
`exact_terminal_distribution` is an analytical terminal projection, and
`sampled_collapse` records an actual sampled outcome and post-measurement collapse.
Exact traces reject sampled outcomes by invariant, while sampled traces reject exact
probability records. A measurement event can attach only to a `MEASURE`
operation with the same operation ID, targets, and key. Targets must be unique and
fit the snapshot width. Exact records have exactly $2^n$ finite, non-negative
probabilities for $n$ targets, and those probabilities must sum to one within an
absolute tolerance of $10^{-12}$. The reference simulator emits exact
probabilities without collapsing the state vector. The sampled trajectory backend
uses a private seeded pseudorandom generator, samples one target-order outcome,
zeros incompatible amplitudes, and renormalizes before any later operation.

At the source boundary, `result = observe(q)` lowers to one `MEASURE` operation
with `ObservationReason.EXPLICIT`; returning `result` reuses that declared
classical result rather than inserting another observation. A discarded
`observe(q)` remains a trace/readout observation but is absent from the returned
classical output. Exact execution raises `A202` if a quantum operation follows an
observation. Sampled collapse is available only when the caller explicitly passes
`SampledExecutionRequest`; runtime never switches execution modes implicitly.

Every per-operation `MeasurementEvent` serializes `scope = marginal`: its exact
probabilities describe only that operation's targets. They do not encode returned
classical correlation by themselves.

When runtime executes a `LogicalCompilationResult`, its `ReadoutPlan` maps lowered
observations and preserves the structured `ReturnShape`. Runtime returns one
`ExactClassicalDistribution` with `scope = joint_return` over its ordered classical
leaves only. This preserves correlations: Bell results in order `(left, right)` are
$00 \mapsto 0.5$, $01 \mapsto 0$, $10 \mapsto 0$, and $11 \mapsto 0.5$, not two
unrelated 50/50 records. Discarded observations remain trace events but are absent
from that public distribution.

`LogicalRunResult.returned_quantum_values` contains one `ReturnedQuantumValue` per
quantum return leaf, with its logical ID, allocated slot, and display name. It is a
handle into `pre_observation_state` / retained analytical state, not a copied
single-qubit state. A returned `Qubit` is not observed and may remain entangled
with other returned quantum values. A quantum-only or `None` return exposes no
classical distribution; a mixed return exposes both the joint classical artifact
and quantum handles.

Per-observation exact probabilities are marginals. The complete returned classical
result is a separately calculated joint distribution.

`SampledLogicalRunResult` is deliberately distinct from `LogicalRunResult`. Its
optional `SampledClassicalResult` carries ordered result IDs, one `SampledShot` per
independently initialized trajectory, joint counts, bit order, and seed. Counts use
the same `targets_lsb_first` indexing convention as exact distributions, but are
empirical observations rather than analytical probabilities. Sampled logical runs
cannot expose a single retained quantum handle, including for one shot: the public
result shape remains trajectory-oriented and does not vary with shot count, while
multiple shots do not share one physical final state vector.

`DensityMatrixLogicalRunResult` is deliberately distinct from both state-vector
result types. It retains the `DensityMatrixResult`, returned quantum slot handles,
and—when classical leaves exist—both
`physical_classical_output_distribution` and
`reported_classical_output_distribution`. The physical distribution is projected
from density diagonal elements. The reported distribution applies a configured
binary readout channel independently to each distinct observation before repeated
return aliases are projected, so one physical result is never independently
noisified twice. Without readout noise the two distributions are equal. Readout
noise never changes the retained density matrix.

`DensityMatrixResult` now also records immutable modeled noise-application
evidence: `gate_noise_events` for configured post-gate channels and
`idle_decoherence_events` for schedule-derived idle intervals. These are evidence
records for what executable model applications were performed; they are not
standalone causal attribution percentages.

Runtime exposes `build_density_noise_impact_report(...)` as an explicit,
read-only projection from a completed `DensityMatrixLogicalRunResult`.
`DensityMatrixLogicalRunResult` now retains a runtime-owned immutable
`DensityExecutionProvenanceSnapshot` built inside supported execution paths. It
captures circuit identity, actual backend identity, optional schedule summary,
optional idle-decoherence profile, executable gate-noise bindings, readout
policy, simulator evidence linkage, and classical distribution linkage. The
report helper derives provenance from this snapshot rather than from a retained
raw `DensityMatrixExecutionRequest`.

Runtime also exposes `build_bare_reliability_report(...)` for the bare
reliability v0.1 milestone. It consumes a `DensityMatrixLogicalRunResult`, a
semantic `ClassicalAcceptanceCriterion`, a `ReliabilityGoal`, and an explicit
selection between the physical and reported classical distributions. The helper
binds accepted outcomes to the exact `joint_return` classical distribution in
`targets_lsb_first` order and reports the exact model-relative acceptance
failure mass for the selected distribution. It does not infer a hardware
guarantee, a confidence interval, or a protection plan.

Status is explicit. Classical-only density runs can produce `SUPPORTED` or
`INDETERMINATE` bare-reliability reports when the runtime coverage snapshot is
complete enough. Missing coverage, unsupported executable features, or retained
coverage issues produce `INCOMPLETE_MODEL`. Quantum-only or hybrid-return runs
produce `UNSUPPORTED`. The current slice treats the ideal-only two-qubit
operation evidence as a completeness issue, so CX-based exactness remains a
model-relative assumption rather than a hardware claim.

This guarantee is intentionally scoped: supported runtime construction rejects
accidental mismatches across circuit/schedule/backend/readout/evidence
artifacts. Hostile in-process Python fabrication and cryptographic attestation
are out of scope.

The helper recomputes an ideal baseline by re-executing the same compiled
circuit with executable noise disabled. Under current semantics, schedule data
drives idle-noise evolution only; ideal replay does not execute
schedule-dependent idle decoherence. Comparison provenance therefore records
both backend identities and the ideal-baseline mode, and preserves noisy
schedule summary evidence (`program_id`, operation fingerprint, and
`peak_duration_ns`) when a noisy schedule was used. Schedule and
idle-decoherence provenance are paired: either both are present or both are
absent.

## Reset

`RESET` is a non-unitary IR operation with one uncontrolled target. Exact
state-vector execution rejects any reset with `A203`: a reset of an entangled value
is a channel, not a unitary transformation of one pure state vector. The sampled
trajectory backend implements reset by internally sampling and collapsing the
target, conditionally applying `X` for an internal outcome of `1`, and leaving the
target in $|0\rangle$. This internal measurement is not a user-visible
`MeasurementEvent`; a sampled trace records a `ResetEvent` with the operation ID,
target, and internal outcome. Exact traces reject reset evidence.

Source `reset(q)` lowers to that operation while preserving the existing logical
value identity. `reset(q)` changes the state of the existing managed quantum value
to $|0\rangle$; it does not create a new `Qubit`. It is valid inside a composed
`None`-returning helper, but it does not make the value's slot reusable under the
current dense no-reuse allocation policy.

Exact density-matrix execution implements the reset channel

$$
\rho \longmapsto \operatorname{Tr}_q(\rho) \otimes |0\rangle\langle0|_q.
$$

The tensor placement follows the backend's qubit ordering. This makes explicit why
resetting one member of an entangled state disturbs its correlations with live
values.

## Executable one-qubit noise contracts

`NoiseProfile` remains descriptive planning metadata. Its `GateNoise.channel`
strings are not executable instructions and simulators never infer a channel from
them. `ExecutableNoiseModel` is a separate `ariadion-noise`, provider-neutral
boundary. It contains typed `BitFlipChannel`, `PhaseFlipChannel`,
`DepolarizingChannel`, `AmplitudeDampingChannel`, and `PhaseDampingChannel` values.
Each supplies an ordered, trace-preserving set of one-qubit Kraus operators for

$$
\mathcal{E}(\rho) = \sum_k K_k \rho K_k^\dagger.
$$

`GateChannelBinding` binds one such channel to public `OneQubitGate`, not a Python
marker name or allocated `OpCode`. The density backend locally maps ideal `X`, `H`,
`Z`, `RX`, `RY`, and `RZ` operations to those categories, runs the ideal gate, then
applies its channel. `CX` is intentionally ideal-only until a correct multi-qubit
channel representation exists. `BinaryReadoutChannel` instead models the classical
outcome probabilities $P(\widetilde{b}=1\mid b=0)$ and
$P(\widetilde{b}=0\mid b=1)$; it is model-level post-observation data, not a
density-matrix gate channel.

For inspectability, every executed one-qubit channel application is recorded as a
`GateNoiseApplicationEvent` with operation ID, target slot, gate category,
channel snapshot, and deterministic application order under the fixed
`ideal_then_channel` ordering.

> A noise profile describes assumptions. An executable noise model defines
> mathematical channels that a simulator can apply.

`NoiseBindingResult` records a typed executable model, assumptions, and all
unsupported `NoiseFeature` values. Every custom channel is validated for a finite
2×2 Kraus representation and $\sum_k K_k^\dagger K_k=I$ before density execution.
It does not select a backend or cause the state-vector simulator to apply a channel.

Density observations are terminal analytical projections, as in exact
state-vector execution. Exact density reset is supported even for entangled
targets. Current traces are amplitude-only; enabled `TraceCaptureOptions` with a
`DensityMatrixExecutionRequest` is rejected with `A205` until a density-trace
contract exists.

> T1/T2 constants are not themselves per-operation error probabilities; a
> schedule and elapsed duration are required before they become executable
> decoherence channels.

`IdleNoise(t1_ns, t2_ns)` therefore remains descriptive. No scheduling or
time-derived amplitude/phase-damping conversion exists in this slice. A
`SimulationRequest` distinguishes ideal `NONE` execution, `DECLARED` typed model
or reference provenance, and future `DEVICE_PROFILE` reference provenance. It
rejects a model/reference for `NONE` and a `DECLARED` request with neither.

### Measurement bit order

Measurement data uses the fixed `targets_lsb_first` convention. For a target
tuple `(q0, q1, ..., qN)`, target `targets[i]` maps to outcome bit `i`; therefore
`targets[0]` is the least-significant bit in an exact probability index. For
example, measuring targets `(q0, q1)` in a state with `q0 = 1` and `q1 = 0`
places all probability at index `1` (`0b01`). Sampled outcome tuples remain in
target order, so `outcome[i]` belongs to `targets[i]`. Consumers must use the
serialized `MeasurementEvent.bit_order` value instead of inferring target mapping
from a rendered binary string.

## Per-step inspection

Consumers can explicitly project a captured `ExecutionTrace` into a
`TraceInspection` with `inspect_execution_trace()`. Trace capture alone does not
perform Theonoe analysis. Each inspection step binds its immutable IR operation
identity and source reference to Theonoe's before/after state reports, basis-state
changes, reduced density matrices, purity, and entanglement transition. This is a
read-only derived artifact: it never mutates the trace or simulator state. See
[Theonoe trace inspection](inspection.md) for the inspection data and separability
semantics. See the [trace debugger contract](debugger.md) for the structured
frontend projection and CLI navigation rules.

## Immutability and metadata

All contract objects are frozen dataclasses with tuple-backed collections. Public
snapshots reject mutable amplitude lists, so consumers cannot observe simulator
internals changing after a trace is captured. Optional `ExecutionMetadata` and
`ResourceMetric` records carry execution mode, seed, timing, and resource values
without requiring a specific simulator or provider implementation.

## Serialization and versioning

`ExecutionTrace` uses `schema_version = 5`. Version five adds sampled collapse
outcomes and reset trajectory evidence while retaining version four's structured
`OperationProvenance.call_stack` shape used to separate a callee definition source
from each invocation frame. Older traces are rejected rather than silently
interpreted under the current exact, sampled, reset, and provenance semantics. All
contract records provide
`to_dict()` and canonical `to_json()` output. Consumers must reject unsupported
future schema versions rather than guessing their meaning. Additive optional fields
are preferred for compatible evolution; semantic changes require a new schema
version. Canonical JSON is strict: it never emits `NaN` or infinity values.
