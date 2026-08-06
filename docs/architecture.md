# Architecture

## Product boundary

Ariadion is both a programming model and an interactive environment. The initial architecture keeps the semantic core independent of any particular IDE, simulator, or cloud provider.

## Dependency direction

```text
ariadion-core
    ├── ariadion-language ──> ariadion-semantics ─┐
    ├── ariadion-ir ───────────────────────────────┼── Daidalon ──> ariadion-runtime
    └── ariadion-syntax ───────────────────────────┘   (future frontend input)

ariadion-runtime ──> simulator / Theonoe / visualization

Ariadion SDK ───────────────────────────────────────> language, semantics, and runtime
```

The compiler produces immutable semantic IR. Runtime backends consume IR. Debuggers
and visualizations observe execution artifacts but do not change source semantics.
`ariadion-core` owns neutral identity and source-location contracts so the language
model and IR remain siblings. Daidalon consumes the hand-built `LogicalProgram`
contract today, preserves source references in lowered operations and diagnostics,
and assigns distinct IR-operation IDs for generated compiler output.

`ariadion-syntax` currently depends only on `ariadion-core`. A future resolved and
typed source-semantic model will bridge Python-compatible extension syntax into
Daidalon without making the syntax package depend on IR, runtime, simulators, or
Theonoe. `ariadion-semantics` depends on `ariadion-core` and the public
`ariadion-language` basis/angle contracts; Daidalon depends on it to lower logical
values and instructions, while its reliability contracts remain planning-only
inputs for later compiler stages.

## Frontend and managed allocation

The public language direction is a managed Python quantum extension. Programmers
create and manipulate logical quantum values; allocation, reuse, layout, and
physical-resource mapping are compiler responsibilities. The intended frontend is:

```text
Python-compatible Ariadion source
    ↓
Python AST and Ariadion extension nodes
    ↓
resolved quantum values and effects
    ↓
typed ownership and observation semantics
    ↓
logical operation schedule
    ↓
reliability analysis
    ↓
protection and allocation plan
    ↓
allocated CircuitIR
    ↓
simulator or hardware backend
```

The Python parser retains ownership of ordinary Python. Ariadion recognizes only
explicit quantum constructs, preserving exact original source ranges and identities
through transformation. A standalone parser for `program name` and `qubits data[2]`
is not on the current path.

The allocated `CircuitIR` continues to use dense integer targets and an explicit
`qubit_count`; those are compiler results. Daidalon now exposes a
`LogicalSlotAllocationPlan` beside the resulting IR. The first policy,
`dense-no-reuse-v1`, maps declaration order to execution slots 0, 1, 2, 3 and sets
both peak live and allocated counts to the number of declared logical values. It
deliberately does not infer lifetimes or reuse slots. This is not a physical or
protected allocation: a later physical plan may map one source `Qubit` to many
hardware qubits. Later allocation artifacts can support diagnostics, resource
reporting, trace navigation, and hardware mapping. Before a future optimized
allocation, a schedule makes duration and idle-time assumptions explicit;
reliability analysis compares its estimate to a requested failure budget; a
protection-and-allocation plan can then select a feasible bare or protected
realization.

At the public boundary, `Qubit` is already a logical value and `Bit` is a distinct
classical observation result. `LogicalQubitId`, `ClassicalBitId`,
`LogicalQubitValue`, and `LogicalOperationId` are compiler-semantic identities;
allocated slots and integer targets are backend-facing facts. No public `Qubit`
constructor accepts a physical or simulator location. Its API must not expose
whether its realization is bare, mitigated, error-detected, or fault-tolerantly
protected. Those are compiler-plan facts, not source-value representations.

## Reliability planning and protection boundaries

`ariadion-semantics` contains immutable contracts for a `ReliabilityGoal`, a
layered `NoiseProfile`, a composable `SimulationRequest`, and a descriptive
`ProtectionPlan`. They freeze future compiler inputs and outputs only: they do not
simulate channels, ingest backend calibration, select a code distance, lay out a
surface code, or map a source `Qubit` to physical qubits.

The future planner's decision process is intentionally model-dependent:

1. Compile and schedule the logical algorithm.
2. Estimate unprotected failure under the selected noise profile.
3. Compare the estimate with the reliability goal.
4. Use a bare realization when it satisfies the goal.
5. Otherwise evaluate compatible protection candidates.
6. Reject candidates whose assumptions place them above threshold.
7. Estimate code distance, physical qubits, runtime, and total failure.
8. Return Pareto-optimal feasible plans.
9. Report when no supported plan meets the goal.

The decision must account for the algorithm schedule, noise profile, backend
architecture, QEC code, decoder, error budget, operation count, idle time,
measurement count, correlations, and leakage. It must not embed one universal QEC
threshold constant. `ProtectedRealization`, `EncodedQubitPlan`, or
`FaultTolerantRealization` are appropriate names for a future encoded realization;
`LogicalQubit` is not, because it collides with the source-semantic term.

## Simulation requests are composable

A future `SimulationRequest` is a planning contract, not a promise that one
numerical engine can evaluate every combination. It keeps independent dimensions
separate rather than compressing them into one fidelity label:

| Dimension | Contract | Examples |
| --- | --- | --- |
| Numerical evolution | `EvolutionModel` | State vector, density matrix, stochastic trajectories, stabilizer methods. |
| Noise provenance | `NoiseModelOrigin` | No noise model, declared assumptions, device-profile-derived assumptions. |
| Noise capabilities | `NoiseFeature` tuple | Gate channels, idle decoherence, readout errors, leakage, correlations. |
| Protected realization | optional `ProtectionPlan` | Bare, mitigated, error-detected, or fault-tolerant planning result. |

Likely implementations differ by requested dimensions: state vectors for ideal pure
states, density matrices for exact small mixed-state circuits, stochastic
trajectories for larger noisy circuits, stabilizer-specialized simulation for
compatible QEC circuits, and dedicated encoded-QEC simulation for syndrome rounds
and decoders. Only the dependency-free ideal state-vector reference simulator
exists today; neither noisy nor protected execution is implemented by these
contracts.

## Object model

Objects clarify ownership, invariants, and relationships; they do not justify
elaborate inheritance trees. See [Object model, ownership, and identity
boundaries](object-model.md) for aggregate ownership, immutable value objects,
stable cross-layer identity, composition guidance, future substitution ports, and
native-language modeling rules.

## Packages

### `ariadion-language`

A small width-based Python builder for the current vertical slice. It records
already allocated integer-target operations, including explicit degree, radian,
and turn-based rotation angles. Alongside the builder, the package exposes
immutable public `Qubit`, `Bit`, `Basis`, and `basis` domain values without adding
them to the width-based API. The builder is a compatibility and migration
mechanism; its next prototype will operate on `Qubit` values instead of requiring
`Program(width)`.

### `ariadion-semantics`

Immutable pre-allocation contracts for logical quantum values, `LogicalProgram`,
gate-shaped and typed rotation `QuantumInstruction` values, observations, declared
`ObservationResultValue` results, tagged recursive return structure, function
effects, reliability goals, layered noise profiles, composable simulation requests,
and protection-plan descriptions. It depends on `ariadion-core` plus shared public
language angle/basis contracts and contains no allocated integer targets, circuit
width, backend policy, noise engine, QEC planner, or lowering. Daidalon consumes
the logical program contracts for the current declaration-order allocation slice;
lifetime analysis, scheduling, reliability analysis, and optimized allocation remain
future work.

### `ariadion-syntax`

Immutable token and source-contracts for extensions embedded in Python-compatible
source. It preserves exact spelling, basis expressions, angle suffixes, complete
source ranges, and snapshot syntax-node IDs with optional durable editor IDs. Its
schema-v3 named-register document model remains compatibility data, not the future
public grammar. It does not parse all of Python, resolve names, allocate resources,
calculate canonical values, or depend on compiled IR. See [the syntax
specification](../specs/syntax.md).

### `ariadion-core`

Shared identity, source-reference, source-range, and deterministic serialization
contracts. `SourceRef` serializes its canonical `SourceOperationId` alongside an
optional compatibility `SnapshotOperationId`, preserving both identity forms across
semantic and builder-derived artifacts. It has no dependency on language syntax, IR,
compilers, or backends.

### `ariadion-ir`

Stable dataclasses for qubits, operations, circuits, IR provenance, and canonical
rotation radians with optional source-display metadata. Provider adapters should
target this layer rather than source objects. Its integer targets and
`CircuitIR.qubit_count` represent an allocated circuit, not user-written resource
allocation.

### `daidalon`

Validates resolved quantum programs, creates an explicit deterministic
`LogicalSlotAllocationPlan` plus `ReadoutPlan`, and lowers current logical gate and
Z-basis observation instructions plus typed logical rotations to semantic IR.
Lowered `MEASURE` operations carry declared result identity, basis, and reason as
`ObservationMetadata`; `ReadoutPlan` retains structured returns rather than
inferring output type or nesting from operation order. Typed rotations preserve
source-unit metadata and canonical radians through existing `RX`/`RY`/`RZ` IR.
The current `dense-no-reuse-v1` policy is intentionally not lifetime analysis.
Future compiler passes will include
canonicalization, decomposition, routing, scheduling, bare-execution estimation,
protection planning, resource estimation, physical allocation, and backend-specific
lowering.

### `ariadion-simulator`

A dependency-free state-vector reference backend. It favors clarity and correctness
over performance, including standard allocated-IR `RX`, `RY`, and `RZ` matrices over
canonical radians. Exact logical execution permits only terminal observations and
retains the analytical amplitude state while runtime calculates a distribution; it
does not sample or collapse the state. When explicitly enabled, it retains raw
immutable amplitude transitions, but it does not depend on runtime trace contracts
or interpret those states.

### `theonoe`

Builds inspectable snapshots: basis probabilities, amplitudes, phase, reduced
density matrices, purity-based separability facts, and explicitly heuristic
subsystem groups. Runtime exposes an explicit projection from immutable execution
traces to these analyses; Theonoe neither mutates traces nor controls simulation.
For rotation steps, it accepts primitive operation facts alongside an inspected
transition to produce structured exact effects and a separately labeled
educational interpretation. It does not import runtime trace contracts.

### `ariadion-visualization`

Turns semantic IR and execution snapshots into textual or structured views. The IDE should consume structured view models rather than scrape rendered strings.

### `ariadion-runtime`

Coordinates compilation, execution, inspection, and rendering. It is the first
vertical slice used by the CLI, examples, and future Studio. For a compiled logical
program, it combines simulator amplitudes with structured `ReadoutPlan` classical
leaves to return one joint `ExactClassicalDistribution`, preserving correlations
rather than exposing independent marginal observations. It separately exposes
returned quantum values as handles into the retained state, not copied qubit states.

It also owns the versioned schema-v3 execution-trace contract consumed by debugger
and Studio clients. It adapts simulator raw capture into that contract and projects
it through Theonoe only when a consumer explicitly requests inspection, so capture
and interpretation remain independently selectable. Measurement events distinguish
an analytic terminal projection from a future sampled execution, and the trace's
retained analytical state is not a physical post-measurement state. Its
frontend-neutral `TraceDebuggerSession` and `TraceStepViewModel` compose IR, trace,
and inspection data without managing terminal interaction.

### `ariadion-cli`

Loads a Python file's top-level program builder and provides trace rendering plus
interactive step navigation. Its terminal renderer consumes runtime view models;
Studio can reuse those models without scraping CLI text.

## Near-term vertical slice

```text
write or hand-build -> validate -> logical slots/readout -> lower -> simulate -> trace -> inspect
```

A change is considered vertically complete only when it can be exercised from the SDK and covered by a runtime-level test.

For the current exact terminal-observation path, the runtime calculates a joint
classical distribution without sampling or mutating the retained analytical state.
This is not physical post-measurement state evolution. Sampled collapse and
mid-circuit feedback remain separate execution capabilities.

A function return is a structured semantic artifact, not merely an ordered list of
identifiers. Classical observation results and returned quantum values may coexist,
and their Python tuple structure is preserved independently of allocation or
measurement order. Per-observation exact probabilities are marginals; the complete
returned classical result is a separately calculated joint distribution.

## Research references

The evidence, assumptions, and limits for future noise modeling live in
[noise-modeling research](research/noise-modeling.md). Threshold, leakage, empirical
QEC, and resource-planning evidence lives in [fault-tolerance and resource-planning
research](research/fault-tolerance-and-resource-planning.md). Future instruction
forms and adaptive physical realization evidence live in
[adaptive-physical-realization research](research/adaptive-physical-realization.md).
All records cite primary papers or official technical documentation consulted on
2026-08-06.
