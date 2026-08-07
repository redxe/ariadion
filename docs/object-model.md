# Object model, ownership, and identity boundaries

## Purpose

Ariadion uses objects to clarify ownership, invariants, and relationships. It does
not use classes to create elaborate inheritance trees. The preferred blend is:

- object-oriented at package and aggregate boundaries;
- value-oriented for domain data;
- functional for compiler transformations and analysis; and
- composition-heavy as capabilities grow.

This document guides future language, Studio, provider, and Friend Compute work.
It is a design boundary, not a mandate to refactor stable working code before a
new feature needs the abstraction.

## Ownership and mutability

Every invariant needs one clear owner. Other layers may observe or project that
owner's data but must not silently repair, reorder, or reinterpret it.

| Aggregate root | Mutability | Owns | Does not own |
| --- | --- | --- | --- |
| `Program` | Mutable while building | Source declarations, source operations, and source construction order | Compiled semantics or execution results |
| `QuantumFunction` | Immutable wrapper with fresh capture traversals | A Python function reference, capture policy, source-provider boundary, and immutable captured `LogicalProgram` or `LogicalModule` values | Invocation of the function body, IR, allocation, or execution results |
| `LogicalProgram` | Immutable | Declared logical values, observation-result values, tagged return shape, quantum instructions, and logical-reference invariants | Slots, circuit width, backend policy, or execution results |
| `LogicalModule` | Immutable | Entry program, reachable programs, call bindings, and acyclic call-graph invariants | Python function objects, slots, circuit width, or execution results |
| `ExpandedLogicalProgram` | Immutable compiler artifact | Invocation-specific values, expanded non-call instructions, return aliases, call-expansion evidence, and escape evidence | Source capture, slot decisions, or runtime state |
| `CircuitIR` | Immutable | Qubit layout, compiled operation order, IR provenance, and validated observation metadata | UI formatting, trace continuity, or backend policy |
| `ExecutionTrace` | Immutable | Execution metadata, initial snapshot, contiguous operation occurrences, state history, and observation execution kind | State interpretation or navigation |
| `TraceDebuggerSession` | Immutable | Current trace-step selection and frontend-ready projection | Terminal input, source mutation, or simulation |
| Theonoe analysis | Immutable | State reports, transitions, exact effects, and educational interpretations | Trace capture, execution policy, or rendering |

`TraceDebuggerSession.to_dict()` already produces the current serialized debugger
document from a matching `CircuitIR`, `ExecutionTrace`, and `TraceInspection`. It
validates those links rather than let a frontend combine arbitrary artifacts.

The practical question for every new rule is: **which object is allowed to
guarantee this invariant?** For example, operation order belongs to `CircuitIR`,
trace continuity belongs to `ExecutionTrace`, and one-based presentation numbering
belongs to a frontend projection rather than the trace itself.

`QuantumFunction` is a deliberate boundary rather than a callable-program proxy.
Ariadion reads the Python AST of a quantum function. It does not execute the
function body to construct the program. Calling the wrapper directly is rejected;
`run()` captures its immutable `LogicalModule` and executes only the resulting
compiled artifacts. Capture does not retain a persistent source-only cache because
relevant global bindings can change; a future cache must fingerprint deterministic
binding classifications rather than use Python object IDs.

## Invalid-state strategy

Python cannot make every invalid state impossible at the type level. Ariadion
should nevertheless make invalid combinations difficult to construct by grouping
required data into small, self-validating immutable value objects.

For example, the current logical rotation-specific value object keeps a unit-bearing
`SemanticAngle` separate from the allocated-IR canonical radians and optional source
display metadata. A `LogicalRotationOperation` must use that typed semantic value
rather than an untyped parameter dictionary:

```python
@dataclass(frozen=True, slots=True)
class LogicalRotationOperation:
    id: LogicalOperationId
    axis: RotationAxis
    target: LogicalQubitId
    angle: SemanticAngle
    source: SemanticSourceRef | None = None
```

A constructor or factory that accepts `LogicalRotationOperation` can validate its
relationship once, rather than forcing every compiler, runtime, and UI consumer to
recheck unrelated optional fields. The same technique applies to measurement
configuration, classical conditions, basis descriptors, backend requests,
breakpoints, and sampled versus exact result records.

`ObservationMetadata` is another current example: it belongs only on `MEASURE`, its
result ID must agree with the operation key, and its basis/reason must travel with
the lowered operation. This is not an argument for a gate-class hierarchy. It is an
argument for keeping concepts that must remain consistent in the same validated
object.

## Composition over inheritance

Do not build a taxonomy such as `SingleQubitOperation`, `RotationOperation`, and
`ControlledOperation` subclasses. Compiler transformations combine orthogonal
concerns: a generated operation can be controlled, parameterized, conditionally
executed, source-linked, and provenance-bearing at the same time.

Prefer an operation assembled from independent concepts as those concepts become
necessary:

```python
@dataclass(frozen=True, slots=True)
class Operation:
    opcode: OpCode
    operands: OperationOperands
    parameters: OperationParameters | None
    condition: ClassicalCondition | None
    source: SourceRef | None
    provenance: OperationProvenance | None
```

The exact names and shapes above are illustrative. Existing `Operation` contracts
remain the source of truth until a feature needs the additional component. New
components should represent an independent semantic axis, have a clear owner, and
validate their own invariants.

## Domain value objects

Small immutable types make ownership explicit and prevent unqualified primitives
from leaking across package boundaries. Existing examples include `Angle`,
`AngleMetadata`, `ProgramId`, `SourceOperationId`, `SourceNodeId`,
SnapshotOperationId`, `IrOperationId`, `ClassicalBitId`, `CallInstanceId`,
`SourceRange`, and `SourceRef`.

Existing and future language work should use value objects where a bare integer or
string would lose meaning, including:

- public `Qubit`, `Bit`, and language-owned `Basis`, plus compiler-only
    `LogicalQubitId`, `ClassicalBitId`, `LogicalQubitValue`, and
    `ObservationResultValue`, `QuantumParameter`, and `NoneReturn` contracts;
- `Basis` and basis expressions;
- `MeasurementKey` and classical conditions;
- `Probability`, `ShotCount`, `ExactClassicalDistribution`, and backend
    identifiers; and
- execution occurrence and breakpoint identities.

At the public boundary, `Qubit()` creates a logical quantum value. It has no
physical construction mode, index, or allocation field. The compiler records its
resolved identity separately before allocation assigns an IR target:

```python
@dataclass(frozen=True, slots=True)
class LogicalQubitValue:
    id: LogicalQubitId
    display_name: str | None
```

A value object validates itself, compares by value, remains immutable, and has a
stable serialized form. Do not create one merely to wrap every primitive; create
one when the name carries a domain invariant or prevents an ambiguous boundary.

## Quantum-value and protection terminology

The following terms identify different layers and must not be substituted for one
another:

```text
Qubit
    Public source-level managed quantum value.

LogicalQubitId
    Internal semantic identity for a Qubit before allocation.

ClassicalBitId
    Internal semantic identity for one declared Bit result of an observation.

AllocatedQubitSlot
    Dense simulator or backend slot selected by Daidalon.

ProtectedRealization
    Error-corrected encoding of one source-level Qubit using
    multiple physical qubits.
```

`Qubit` is logical by definition and never publishes its allocation or protection
representation. `AllocatedQubitSlot` is documentation terminology for an allocated
backend target; it is not a source construction parameter. `ProtectedRealization`
may later be described by an `EncodedQubitPlan` or `FaultTolerantRealization`, but
the name `LogicalQubit` must not be used for that QEC object because it collides
with source-semantic language. The current hand-built logical slice uses one dense
execution slot per declared value under the explicitly limited `dense-no-reuse-v1`
`LogicalSlotAllocationPlan`; it does not infer lifetimes or reuse a slot. This plan
does not imply that one source value maps to one physical qubit. Module compilation
uses `expanded-dense-no-reuse-v1`: it materializes invocation-specific values,
records lifetime and release-safety evidence, then still assigns every expanded
value a unique dense slot. `peak_semantically_live_values` is source-semantic
lifetime evidence; `peak_live_qubits` is the width allocated by a selected policy.
It does not reuse a slot yet.

> **Quantum liveness is not quantum reusability. A value may become unreachable
> while its state remains entangled with live values. Reusing its execution slot
> requires a proven-clean state or an explicit discard/reset capability.**

`QuantumReleaseAnalysis` is a separate immutable artifact. A returned value or
borrowed entry parameter is `retained`; an otherwise dead local is
`discard_required`. `discard_required` records a safety obligation and never
authorizes an allocator to recycle the slot.

`ReliabilityGoal`, `NoiseProfile`, and `ProtectionPlan` are immutable planning
contracts owned by the semantic layer. They describe requested bounds, assumptions,
and a future planner's result; they do not mutate a source `Qubit`, allocate a
physical slot, or implement a decoder.

## Identity across layers

Layers link through stable identifiers, never Python object identity. A source
construct has a neutral `SourceOperationId`; it is not assumed to be a
width-builder operation. The current width-based builder additionally retains its
`SnapshotOperationId` as compatibility data, and an editor may provide a durable
`SourceNodeId`. The semantic, allocated, and execution chain is:

```text
source construct identity
    SourceOperationId
    -> LogicalOperationId (one gate or observation instruction)
    -> one or more IrOperationId values (lowered or generated operations)
    -> trace occurrence

call invocation identity
    LogicalCallOperation
    -> ordered QuantumArgumentBinding values
    -> deterministic CallInstanceId
    -> CallFrameProvenance in OperationProvenance.call_stack
    -> invocation-specific IrOperationId

logical value identity
    source LogicalQubitId definition
    -> ExpandedLogicalQubit / LogicalQubitOrigin / invocation-specific LogicalQubitId
    -> LogicalSlotAllocationEntry / AllocatedQubitSlot
    -> integer IR target

classical result identity
    ClassicalBitId
    -> AllocatedObservation / ObservationMetadata
    -> ReadoutPlan structured classical leaf
    -> ExactClassicalDistribution probability or SampledClassicalResult count bit position

quantum return identity
    LogicalQubitId
    -> ReadoutPlan structured quantum leaf
    -> ReturnedQuantumValue retained-state handle
```

The valid-Python frontend creates each `SourceOperationId` from the captured source
program ID, source construct kind, absolute one-based line and column, and a local
ordinal. It derives those facts from `PythonFunctionSource`, not from a live
`Qubit()` object or Python function-object identity. A source provider can therefore
supply an unsaved IDE buffer while preserving the same source-range contract.

`SourceRef.source_operation_id` is the canonical source-operation field.
`SourceRef.snapshot_operation_id` is an optional compatibility property for a
reference derived from the legacy builder; semantic programs must not fabricate a
snapshot identity. Serialization preserves both fields, with `null` for unavailable
builder compatibility data. `SyntaxNodeId` is required for one parsed source
snapshot but does not promise to survive edits. `SourceNodeId` must survive source
editing when supplied by an editor. `LogicalQubitId` distinguishes a source-level
value from an allocated target. `LogicalOperationId` identifies every
`QuantumInstruction`, including an `Observation`; each observation has a produced
`ClassicalBitId`; `OperationProvenance.parent_logical_operation_ids` preserves its
link to allocated IR. IR IDs distinguish lowered or generated output operations.
Trace steps preserve an ordered occurrence of an IR operation during one execution.

A future `OperationLink` value object may centralize these relationships for
source navigation, persistent breakpoints, compiler provenance, remote result
reconciliation, tutorial checkpoints, and Studio synchronization:

```python
@dataclass(frozen=True, slots=True)
class OperationLink:
    program_id: ProgramId
    syntax_node_id: SyntaxNodeId | None
    source_node_id: SourceNodeId | None
    source_operation_id: SourceOperationId | None
    logical_operation_id: LogicalOperationId | None
    ir_operation_id: IrOperationId
    execution_occurrence_id: ExecutionOccurrenceId | None
```

This is a future extension. It must not replace existing identifiers until it can
represent every current relationship without information loss.

`LogicalCallOperation` deliberately preserves a callable boundary. It names the
callee `ProgramId`, ordered bindings from callee parameter IDs to caller logical
value IDs, and an optional scalar quantum result alias. Daidalon expands that
semantic operation before allocation; it does not mutate a callee operation's
`SourceRef.program_id` to look as though the operation was written at the caller
call site. The source remains the definition, while each `CallFrameProvenance`
records an invocation separately. A qubit declaration inside a reusable quantum
function is a definition. Each function invocation instantiates that declaration as
a distinct logical quantum value unless the value is a bound parameter alias.
Returning a `Qubit` transfers the same logical quantum value across the function
boundary. It never copies quantum state.

## Exact and sampled observation execution boundary

`ReadoutPlan` owns the bridge between compiled observations and the source-preserved
structured return. For the current exact state-vector path, runtime calculates an
`ExactClassicalDistribution` from retained analytical amplitudes for all classical
return leaves together. Its `joint_return` scope does not manufacture independent
marginals and does not mutate the analytical state to a sampled post-measurement
state. `ReturnedQuantumValue` records a logical ID, allocated slot, and display name
as a handle into that same retained state; it is not a copied single-qubit state.

A function return is a structured semantic artifact, not merely an ordered list of
identifiers. Classical observation results and returned quantum values may coexist,
and their Python tuple structure is preserved independently of allocation or
measurement order. Per-observation exact probabilities are `marginal`; the complete
returned classical result is a separately calculated joint distribution.

`MeasurementEvent.execution_kind` makes that distinction explicit:
`exact_terminal_distribution` is an analytic terminal projection, while
`sampled_collapse` contains a target-order outcome and a collapsed trajectory
state. The exact engine rejects any non-measurement operation after the first
observation. Explicit `SampledExecutionRequest` execution starts every shot from
$|00\ldots0\rangle$, samples sequentially with a private seeded generator, and
permits later quantum gates. It returns sampled result types rather than adding
empirical counts to `LogicalRunResult`.

`RESET` is likewise split by execution model. Exact pure-state-vector execution
rejects it with `A203`; a sampled trajectory internally collapses the target and
conditionally applies `X` to establish $|0\rangle$, recording `ResetEvent`
evidence rather than a user-visible measurement result. A future density-matrix
backend can model the exact channel
$\rho \mapsto \operatorname{Tr}_q(\rho) \otimes |0\rangle\langle0|_q$. Reset of
an entangled value can disturb live correlations, so neither reset evidence nor a
semantic lifetime endpoint implies reusable allocation capacity.

## Ports and substitution boundaries

Use a `Protocol` only where multiple implementations are expected and a consumer
should not care which one it receives. Candidate ports include execution backends,
trace stores, source-document providers, compiler passes, diagnostic sinks,
tutorial-progress stores, and debugger renderers.

For example, provider work should depend on an execution port rather than a
simulator class:

```python
class ExecutionBackend(Protocol):
    def execute(
        self,
        circuit: CircuitIR,
        request: ExecutionRequest,
    ) -> BackendExecution:
        ...
```

Reference simulation, shot simulation, hardware adapters, and distributed Friend
Compute backends can then be substituted at that boundary. Do not create an
interface merely because a concrete class exists.

## Compiler transformations

Daidalon should grow as a visible pipeline of composable transformations rather
than one mutable compiler object with many unrelated responsibilities. A future
pass boundary can look like:

```python
class CompilerPass(Protocol):
    name: str

    def run(self, context: CompilationContext) -> CompilationContext:
        ...
```

Each pass should return a new immutable artifact or context, add diagnostics,
preserve or extend provenance, and expose optional analysis data. Likely stages
include validation, name resolution, type checking, angle normalization, call
expansion, basis lowering, ownership and observation analysis, lifetime analysis,
scheduling, reliability analysis, protection planning, allocation, decomposition,
routing, resource estimation, and backend lowering.

The relevant principle is not the exact `CompilationContext` type. It is that a
pass has declared inputs, outputs, diagnostics, and provenance effects. Studio can
then explain the path from source program through resolved and typed semantic
models to normalized and backend-specific IR.

## State machines for interactive workflows

Use explicit state objects or discriminated value states for workflows with real
lifecycle transitions. Good future candidates are tutorial progress and
asynchronous provider execution:

```text
NotStarted -> ShowingConcept -> WaitingForEdit -> Running
    -> ExplainingResult -> Completed

Queued -> Running -> Completed
       -> Failed
       -> Cancelled
```

This is preferable to unrelated boolean fields such as `has_started`, `is_running`,
and `has_completed`. Simple synchronous code does not need the pattern; apply it
when transitions, persistence, cancellation, or recovery need independent tests.

## Domain data and rendering

Domain objects must not acquire terminal or Studio layout responsibilities.
`CircuitIR` does not own ASCII widths, colors, panels, or human-friendly phase
formatting. `StateTransition` and `RotationExplanation` do not own beginner or
expert UI layout.

Use one-way projections instead:

```text
CircuitIR -> CircuitViewModel -> CLI renderer / Studio renderer

StateTransition -> RotationExplanation -> Beginner / expert / Studio presentation
```

The existing trace debugger follows this rule: runtime builds structured view
models, while the CLI renders them without computing new physics. Studio must
consume serialized models rather than scrape terminal text.

## Guardrails

- Prefer composition to inheritance for independent semantic concerns.
- Keep data immutable after a layer has established its meaning.
- Assign each invariant to exactly one aggregate root or value object.
- Use stable IDs in serialized links; never rely on Python object identity.
- Add protocols only at genuine substitution boundaries.
- Preserve source syntax, resolved semantics, and IR as separate models.
- Keep renderers and input handling outside domain and analysis objects.
- Split a class when it changes for unrelated reasons; avoid `Program`, runtime,
  or Studio-session god objects.

## Python-extension language application

The Ariadion Python extension must keep author syntax separate from semantic
meaning and compiled IR. Python owns ordinary Python parsing; extension nodes
preserve Ariadion spelling and source ranges; resolved nodes preserve logical-value
bindings; typed nodes establish domain meaning and ownership; lifetime analysis and
observation rules; scheduling, reliability analysis, and protection planning then
inform allocation before IR targets are assigned.

```text
Python AST + extension node
    -> resolved logical-value node
    -> typed/owned semantic node
    -> LogicalProgram / LogicalModule
    -> invocation-aware expansion and lifetime analysis
    -> logical-slot allocation
    -> IR operation
```

For example, `rx(target, deg(190))` retains its source angle, becomes an angle in
the typed model, and lowers to canonical radians plus source metadata in IR. A
future `190deg` extension literal must lower into that same model. Extension nodes
must not double as `CircuitIR` operations.

`Qubit` to `Bit` is an observation boundary in semantic analysis. An explicit
measurement models timing-sensitive algorithm behavior; a terminal typed classical
return may create an implicit observation. `Qubit` truth testing must not silently
observe a value, and a Python alias must never create another quantum state.

The schema-v3 named-register source AST remains compatibility data. The current
logical slice is now reachable through the valid-Python `@quantum` AST frontend as
well as hand-built data. The current frontend composes local-value callees and
scalar `Qubit` result aliases through explicit logical bindings. Call expansion and
lifetime analysis preserve definition, invocation, and expanded-value identities
before dense non-reusing allocation. Any future optimized slot-reuse pass must
consume release safety and establish a proven-clean state or explicit discard/reset
capability; source liveness alone is insufficient. Later language milestones include
ownership refinements, resource inference, and only then justified extension syntax
or richer editor support.
