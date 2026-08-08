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

For a sampled collapse, the before and after reports instead describe one physical
trajectory: the outcome appears in the `MeasurementEvent` and the after report is
the collapsed state. A sampled `RESET` has no user-visible measurement event, but
its `TraceStepInspection.reset` preserves the internal trajectory outcome used to
conditionally establish $|0\rangle$ on the target. Resetting an entangled target
can therefore visibly change the inspected state of its partners.

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
associated schema-v5 `ExecutionTrace.schema_version` when storing or exchanging an
inspection. `rotation_explanation` is an additive optional step field. The current
`INSPECTION_SCHEMA_VERSION` is $3$ because inspection serializes structured reset
evidence in addition to the call-stack provenance. Older inspection schema versions
are rejected rather than silently interpreted as the current shape.

## Density noise-impact reports

Theonoe also provides immutable mixed-state noise-impact reporting for
density-matrix execution artifacts. This contract is separate from state-vector
trace inspection: it compares one matched ideal baseline density matrix against a
noisy density matrix and, when present, contrasts physical and readout-reported
classical distributions.

Public report construction consumes simulator-validated density states. If a raw
matrix convenience path is used, it immediately canonicalizes numeric
`int`/`float`/`complex` entries and constructs a simulator-owned
`ValidatedDensityState` before analysis; no public path performs report analysis
from shape-only matrix validation.

Reported metrics include Hilbert-Schmidt distance, computational-basis
population TVD, l1 coherence values/deltas, purity values/deltas, physical output
TVD, and readout-distortion TVD. Computational-basis population and l1 coherence
metrics are explicitly basis dependent.

Metric provenance describes how each numeric value was obtained (for the current
report, numerical metrics are derived from reported states/distributions).
Comparison provenance separately describes how the noisy and ideal baseline
executions were obtained (backend identities, ideal-baseline mode, and noisy
schedule context).

The report also carries structured modeled-event findings from runtime/simulator
artifacts:

- gate-channel applications (`GateNoiseApplicationEvent`),
- schedule-derived idle-decoherence intervals (`IdleDecoherenceEvent`),
- optional readout-channel distortion evidence.

These findings provide inspectable modeled evidence and parameters. They do not
claim additive causal decomposition of total state deviation across events.

The runtime bare-reliability assessment reuses this density noise-impact report
as supporting evidence, but the acceptance-failure calculation itself is a
separate runtime helper. Inspection does not decide supported, incomplete,
indeterminate, or unsupported bare-reliability status on its own, and it does
not promote exact acceptance failure mass into a hardware guarantee.
Readout distortion is reported as a classical output effect and is not represented
as quantum-state damage in the retained density matrix.

Theonoe also provides a derived protection-requirement report built only from an
existing bare-reliability report. It reuses the bare-reliability status, projects
it into a protection-need verdict, and carries compact signed/relative failure-space
metrics plus the supporting bare report. When the existing bare report is
`NOT_EVALUATED` within its own tolerance, the derived report still maps to
`NO_PROTECTION_REQUIRED` with zero required reduction and no suppression.
Non-supported evidence maps to `NOT_ASSESSED` with no metrics. This report does
not select a protection strategy, estimate resources, or allocate qubits.

Event findings enforce exactly one evidence payload matching each declared
`NoiseImpactEventKind`; unrelated extra evidence is rejected. Gate and readout
channel evidence, along with idle-decoherence profile provenance, are retained as
immutable typed snapshots with deterministic `to_dict()` serialization.

When a program has no classical output distribution, output-distribution metrics
are absent rather than encoded as zero-impact values. When distributions are
present and equal, output TVD metrics remain present with zero values.
