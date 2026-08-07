# Architecture

## Product boundary

Ariadion is both a programming model and an interactive environment. The initial architecture keeps the semantic core independent of any particular IDE, simulator, or cloud provider.

## Dependency direction

```text
ariadion-core ──> ariadion-language ──> ariadion-semantics ──> Daidalon
ariadion-core ──> ariadion-ir ───────────────────────────────────> Daidalon
ariadion-core ──> ariadion-syntax

ariadion-core + ariadion-language + ariadion-semantics
    -> ariadion-frontend-python
    -> Ariadion SDK

Daidalon ──> ariadion-runtime ──> simulator / Theonoe / visualization

Ariadion SDK ───────────────────────────────────────> language, semantics, frontend, and runtime
```

The compiler produces immutable semantic IR. Runtime backends consume IR. Debuggers
and visualizations observe execution artifacts but do not change source semantics.
`ariadion-core` owns neutral identity and source-location contracts so the language
model and IR remain siblings. Daidalon consumes the hand-built `LogicalProgram`
contract and AST-captured `LogicalProgram` values today, preserves source references
in lowered operations and diagnostics, and assigns distinct IR-operation IDs for
generated compiler output.

`ariadion-syntax` currently depends only on `ariadion-core`. It remains separate
from the implemented valid-Python frontend. `ariadion-frontend-python` depends
only on `ariadion-core`, `ariadion-language`, and `ariadion-semantics`; it never
imports IR, Daidalon, runtime, simulator, Theonoe, or CLI packages. A future
resolved and typed extension-source model will bridge Python-compatible extension
syntax into Daidalon without making the syntax package depend on those packages.
`ariadion-semantics` depends on `ariadion-core` and the public
`ariadion-language` basis/angle contracts; Daidalon depends on it to lower logical
values and instructions, while its reliability contracts remain planning-only
inputs for later compiler stages.

## Frontend and managed allocation

The public language direction is a managed Python quantum extension. Programmers
create and manipulate logical quantum values; allocation, reuse, layout, and
physical-resource mapping are compiler responsibilities. The valid-Python frontend
captures each function AST into `LogicalProgram` and resolves reachable calls into
`LogicalModule`. Ariadion does not execute either Python body to construct these
artifacts. Its current narrow subset supports local `Qubit()` declarations, aliases,
typed quantum parameters, named intrinsic markers, explicit-unit rotations, typed
terminal returns, and identity-resolved quantum-function calls. The implemented
path is:

```text
Python-compatible Ariadion source
    ↓
ariadion-frontend-python Python AST capture
    ↓
LogicalProgram with source-derived identities and LogicalCallOperation values
    ↓
LogicalModule with explicit callee-parameter bindings
    ↓
invocation-aware call expansion / logical instantiation
    ↓
ExpandedLogicalProgram
    ↓
lifetime analysis
    ↓
release-safety analysis
    ↓
logical-slot allocation
    ↓
allocated CircuitIR
    ↓
simulator or hardware backend
```

Python retains ownership of ordinary parsing. The frontend resolves exact public
marker and `QuantumFunction` identities from the wrapped function's globals and
never evaluates the body, annotations, or angle expressions. Annotation spelling
must also resolve to Ariadion's public `Qubit` or `Bit` class, or the built-in
`tuple` type. It preserves exact original source ranges and source-derived
identities through an explicit source-provider boundary, including in-memory IDE
source. A standalone parser for `program name` and `qubits data[2]` is not on the
current path.

The allocated `CircuitIR` continues to use dense integer targets and an explicit
`qubit_count`; those are compiler results. Daidalon now exposes a
`LogicalSlotAllocationPlan` beside the resulting IR. `compile_logical_module()`
first materializes every reachable call into an `ExpandedLogicalProgram`, analyzes
value lifetimes and release safety, and records call-expansion evidence before
allocating. A qubit
declaration inside a reusable quantum function is a definition. Each function
invocation instantiates that declaration as a distinct logical quantum value unless
the value is a bound parameter alias. `expanded-dense-no-reuse-v1` assigns every
expanded value a dense unique slot; it does not reuse slots. Its
`peak_live_qubits` is an allocated-width fact, separate from
`peak_semantically_live_values` lifetime evidence. Hand-built programs retain
`dense-no-reuse-v1`.

> **Quantum liveness is not quantum reusability. A value may become unreachable
> while its state remains entangled with live values. Reusing its execution slot
> requires a proven-clean state or an explicit discard/reset capability.**

`QuantumReleaseAnalysis` retains returned values and borrowed entry parameters and
marks other locals `discard_required`. That marker records a safety obligation; it
does not make a slot available for reuse under the current allocation policies.
This is not physical or protected allocation: a later physical plan may map one
source `Qubit` to many hardware qubits. Later allocation artifacts can support
diagnostics, resource reporting, trace navigation, and hardware mapping. Before a
future optimized allocation, a schedule makes duration and idle-time assumptions
explicit; reliability analysis compares its estimate to a requested failure budget;
a protection-and-allocation plan can then select a feasible bare or protected
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
`ProtectionPlan`. `ariadion-noise` owns the separate provider-neutral
`ExecutableNoiseModel`: typed one-qubit Kraus channels are bound to public
`OneQubitGate` categories, never allocated `OpCode` values. It also owns the
optional model-level `BinaryReadoutChannel`. This keeps pre-allocation semantics
independent of allocated IR while simulator execution resolves neutral gate
categories locally. `NoiseProfile` remains planning/input metadata: its named
channel strings are never interpreted by a simulator.

`ariadion-simulator` now provides a deliberately small exact density-matrix
backend. `DensityMatrixExecutionRequest` accepts an actual
`ExecutableNoiseModel`, validates every custom one-qubit Kraus channel before
execution, applies the ideal `X`, `H`, `Z`, `RX`, `RY`, or `RZ` operation before
its matched channel, and executes ideal `CX`. It has no two-qubit noise,
device-calibration ingestion, scheduling, code-distance selection, surface-code
layout, or physical-source-`Qubit` mapping.

> A noise profile describes assumptions. An executable noise model defines
> mathematical channels that a simulator can apply.

> T1/T2 constants are not themselves per-operation error probabilities; a
> schedule and elapsed duration are required before they become executable
> decoherence channels.

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
| Noise provenance | `NoiseModelOrigin` plus a model/reference | No noise model, declared executable noise, device-profile-derived noise. |
| Noise capabilities | `NoiseFeature` tuple | Gate channels, idle decoherence, readout errors, leakage, correlations. |
| Protected realization | optional `ProtectionPlan` | Bare, mitigated, error-detected, or fault-tolerant planning result. |

Likely implementations differ by requested dimensions: state vectors for ideal pure
states, density matrices for exact small mixed-state circuits, stochastic
trajectories for larger noisy circuits, stabilizer-specialized simulation for
compatible QEC circuits, and dedicated encoded-QEC simulation for syndrome rounds
and decoders. The current reference backends are ideal state-vector execution and
small exact density-matrix execution with typed one-qubit channels. The latter
accepts only an actual `ExecutableNoiseModel`, never an unresolved model
reference. `SimulationRequest` remains a planning contract: it accepts no
model/reference for `NONE`, requires a typed model or non-empty reference for
`DECLARED`, and requires a reference for future `DEVICE_PROFILE` provenance. When
it carries a typed model, its executable `noise_features` are derived from the
model or must match it exactly. Compiler/runtime binding evidence records
unsupported `NoiseFeature` values explicitly rather than silently dropping them.

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
immutable public `Qubit`, `Bit`, `Basis`, `basis`, and non-executing intrinsic
marker values such as `h`, `cx`, `rx`, `observe`, and `reset`. The builder is a compatibility and
migration mechanism; its next prototype will operate on `Qubit` values instead of
requiring `Program(width)`.

### `ariadion-frontend-python`

The safe valid-Python frontend. It reads a decorated Python function through a
`PythonSourceProvider`, parses its AST, resolves only exact public marker identity,
and produces immutable `LogicalProgram` values with deterministic source-derived
identities, ranges, typed returns, inferred terminal observations, unresolved
`QuantumParameter` inputs, explicit observation-result bindings, semantic resets,
and explicit `LogicalCallOperation` values. Its
`to_logical_module()` traversal captures a resolved acyclic call graph without
executing any body. Callee parameters bind to caller logical values; calls are not
textually substituted. Callable callees may declare local `Qubit()` values, and a
scalar `Qubit` return may bind to one caller assignment name. That name aliases the
returned quantum value; returning a `Qubit` transfers the same logical quantum
value across the function boundary and never copies quantum state. Bare calls remain
`None`-only, while classical or tuple call results and callee observations remain
unsupported. `None`-returning callees may reset caller-managed values. The frontend
has no persistent source-only capture cache, so relevant
global rebinding cannot reuse stale semantics. It never calls the function body or
intrinsic markers.
Its dependencies are limited to `ariadion-core`, `ariadion-language`, and
`ariadion-semantics`; it has no dependency on IR, Daidalon, runtime, simulator,
Theonoe, CLI, or `ariadion-syntax`.

### `ariadion-semantics`

Immutable pre-allocation contracts for logical quantum values, `LogicalProgram`,
gate-shaped and typed rotation `QuantumInstruction` values, observations, declared
`ObservationResultValue` results, `LogicalResetOperation`, tagged recursive return structure, function
effects, reliability goals, layered noise profiles, composable simulation requests,
and protection-plan descriptions. It depends on `ariadion-core` plus shared public
language angle/basis contracts and contains no allocated integer targets, circuit
width, backend policy, noise engine, QEC planner, or lowering. Daidalon consumes
the logical program contracts for call-result aliases, invocation-aware expansion,
and allocation. Scheduling, reliability analysis, and optimized slot reuse remain
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
Z-basis observation instructions, logical resets, and typed logical rotations to semantic IR.
`compile_logical_module()` materializes a `LogicalModule` into an immutable
`ExpandedLogicalProgram`, binds each callee parameter as an alias, instantiates
each callee-local definition per deterministic call instance, analyzes lifetimes,
then allocates every expanded value. It retains the callee definition source on each
generated operation and records invocation frames in IR provenance, with
invocation-specific deterministic IR IDs. Returning a `Qubit` transfers the same
expanded value over the boundary rather than copying quantum state.
Lowered `MEASURE` operations carry declared result identity, basis, and reason as
`ObservationMetadata`; `ReadoutPlan` retains structured returns rather than
inferring output type or nesting from operation order. Typed rotations preserve
source-unit metadata and canonical radians through existing `RX`/`RY`/`RZ` IR.
The `expanded-dense-no-reuse-v1` policy consumes lifetime evidence but intentionally
does not reuse slots. Future compiler passes will include
canonicalization, decomposition, routing, scheduling, bare-execution estimation,
protection planning, resource estimation, physical allocation, and backend-specific
lowering.

### `ariadion-simulator`

A dependency-free reference package with separate state-vector and exact
density-matrix backends. The state-vector path favors clarity and correctness over
performance, including standard allocated-IR `RX`, `RY`, and `RZ` matrices over
canonical radians. Exact logical state-vector execution permits only terminal
observations and retains the analytical amplitude state while runtime calculates a
distribution; it does not sample or collapse the state and rejects general `RESET`
with `A203`. Explicit `SampledExecutionRequest` execution runs independent seeded
trajectories: `MEASURE` samples and collapses the vector, later gates are allowed,
and IR `RESET` uses an internal collapse plus conditional `X` to establish
$|0\rangle$. A sampled trace is exactly one trajectory; multiple-shot trace capture
rejects with `A204`. When explicitly enabled, the state-vector backend retains raw
immutable amplitude transitions, but it does not depend on runtime trace contracts
or interpret those states.

`DensityMatrixExecutionRequest` selects exact mixed-state execution. It begins in
$|0\ldots0\rangle\langle0\ldots0|$, supports ideal `X`, `H`, `Z`, `RX`, `RY`,
`RZ`, and `CX`, then applies a matching typed one-qubit channel after each ideal
single-qubit gate. Density observations are terminal analytical projections;
`RESET` implements the exact trace-and-reprepare channel, including on entangled
targets. Current traces are amplitude snapshots, so requesting enabled trace capture
for density execution is rejected with `A205` rather than serializing fake
amplitudes.

The intended execution-model boundary is explicit:

| Execution model | `MEASURE` | `RESET` |
| --- | --- | --- |
| Exact state vector | Analytical terminal probability only; amplitudes remain retained | Unsupported (`A203`) |
| Sampled state-vector trajectory | Sample one outcome and collapse | Collapse internally, conditionally apply `X`, yield $|0\rangle$ |
| Exact density matrix | Analytical terminal probability only; density remains retained | Exact CPTP trace-and-reprepare channel |

For exact density-matrix execution, reset has the channel semantics
$\rho \mapsto \operatorname{Tr}_q(\rho) \otimes |0\rangle\langle0|_q$ (with
the target tensor placement chosen by the backend). It is not a unitary and can
destroy correlations between the reset target and live values.

### Simulation backend capability and kernel boundary

**Ariadion owns quantum semantics and execution planning; numerical kernels are
replaceable realizations.** `ariadion-simulator` defines array-free
`StateRepresentation`, `SimulationQuery`, `SimulationCapabilities`,
`SimulationBackend`, and `SimulationPlan` contracts. The representation enum is
an execution capability contract and intentionally does not expand the separate,
amplitude-only runtime trace schema.

```text
Simulation intent
    ↓
capability/planning layer
    ↓
reference | NumPy | Numba | GPU | stabilizer | tensor network | distributed
```

The capability/planning layer records a caller-selected backend in an immutable
`SimulationPlan`; it does not select NumPy, an accelerator, or any other backend
automatically. Current reference wrappers are explicitly named
`reference-state-vector`, `reference-sampled-trajectory`, and
`reference-density-matrix`, and they retain the existing tuple-based reference
engines as correctness oracles. Runtime's public `run()` behavior remains on those
reference paths until a later, explicitly designed runtime-selection policy exists.

`ariadion-simulator-numpy` is a separate optional package, so the reference
package remains NumPy-free. Its CPU backends use `complex128` and return existing
immutable `SimulationResult` and `DensityMatrixResult` contracts rather than
leaking arrays. State-vector `X` and `CX` use indexed permutations, `Z` and `RZ`
use diagonal multiplies, and `H`/`RX`/`RY` use local tensor-axis transforms. Its
density kernels apply local $U\rho U^\dagger$ and Kraus maps, row/column
permutations for `CX`, and exact reset without constructing a full-system gate
matrix or superoperator.

`KernelMetadata` exposes the relevant operator structure independently of a
framework: `PERMUTATION`, `DIAGONAL`, `LOCAL_DENSE`,
`CONTROLLED_PERMUTATION`, and `KRAUS_CHANNEL`. This makes a backend's local-kernel
choice inspectable without changing IR syntax or committing the planner to a
specific numerical library.

Exact density results validate Hermiticity, trace one, and positive
semidefiniteness. The explicit absolute positivity tolerance is
`DENSITY_MATRIX_POSITIVITY_ABS_TOLERANCE = 1e-12`; a diagonal-pivoted Cholesky
check rejects materially negative eigenvalue evidence while accepting numerical
error at or below that tolerance.

**Reference backends optimize for transparency and correctness. Performance
backends may use vectorization, JIT compilation, GPUs, tensor networks,
stabilizers, or distributed execution while preserving the same semantic
contract.** None of those later realizations changes whether a request is exact,
sampled, noisy, or approximate; that semantic mode stays explicit in the request
and plan.

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

It also owns the versioned schema-v5 execution-trace contract consumed by debugger
and Studio clients. It adapts simulator raw capture into that contract and projects
it through Theonoe only when a consumer explicitly requests inspection, so capture
and interpretation remain independently selectable. The trace distinguishes
analytical terminal probabilities from sampled outcomes and records sampled reset
evidence. Exact `LogicalRunResult` and sampled `SampledLogicalRunResult` remain
distinct: the former exposes analytical distributions and retained quantum handles,
while the latter exposes independently initialized shots and empirical counts. Its
frontend-neutral `TraceDebuggerSession` and `TraceStepViewModel` compose IR, trace,
and inspection data without managing terminal interaction.

Before lowering, runtime rejects a `LogicalProgram` with unresolved
`QuantumParameter` inputs using `UnboundQuantumParameterError` (`P113`). This
prevents the current standalone exact executor from silently initializing a captured
input as a local $|0\rangle$ value. `run_logical_module()` applies the same rule
only to the module entry: composition binds callee parameters to caller values, not
external runtime state. Trace steps can retain a callee source program different
from the entry circuit and expose the matching invocation stack through debugger
view models.

### `ariadion-cli`

Loads a Python file's top-level program builder and provides trace rendering plus
interactive step navigation. Its terminal renderer consumes runtime view models;
Studio can reuse those models without scraping CLI text.

## Near-term vertical slice

```text
capture safe Python AST or hand-build -> validate -> expand calls -> analyze lifetimes
-> release safety -> logical slots/readout -> lower -> state-vector, sampled, or density execute
-> amplitude trace/inspection when supported
```

A change is considered vertically complete only when it can be exercised from the SDK and covered by a runtime-level test.

For the exact terminal-observation path, the runtime calculates a joint classical
distribution without sampling or mutating the retained analytical state. This is
not physical post-measurement state evolution. The explicit sampled path instead
collapses each trajectory in operation order and can run later gates. It remains
separate from unsupported classical branching, scheduling, calibration ingestion,
multi-qubit noise, leakage, correlations, and QEC.

Inferred observation handles ordinary classical returns. Explicit `observe()`
exists when observation timing itself is part of the algorithm. Source `reset(q)`
changes the state of the existing managed quantum value to $|0\rangle$; it does not
create a new `Qubit`. Both markers are captured from AST and require an explicit
`SampledExecutionRequest` for trajectory collapse/reset execution. Exact
density-matrix execution instead implements reset analytically; neither mode causes
a hidden switch from the default exact state-vector path.

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
