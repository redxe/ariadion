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
| `CircuitIR` | Immutable | Qubit layout, compiled operation order, IR provenance, and semantic operation data | UI formatting, trace continuity, or backend policy |
| `ExecutionTrace` | Immutable | Execution metadata, initial snapshot, contiguous operation occurrences, and state history | State interpretation or navigation |
| `TraceDebuggerSession` | Immutable | Current trace-step selection and frontend-ready projection | Terminal input, source mutation, or simulation |
| Theonoe analysis | Immutable | State reports, transitions, exact effects, and educational interpretations | Trace capture, execution policy, or rendering |

A future serialized debugger document should be an aggregate built from a matching
`CircuitIR`, `ExecutionTrace`, and `TraceInspection`. It must validate those links
rather than let a frontend combine arbitrary artifacts.

The practical question for every new rule is: **which object is allowed to
guarantee this invariant?** For example, operation order belongs to `CircuitIR`,
trace continuity belongs to `ExecutionTrace`, and one-based presentation numbering
belongs to a frontend projection rather than the trace itself.

## Invalid-state strategy

Python cannot make every invalid state impossible at the type level. Ariadion
should nevertheless make invalid combinations difficult to construct by grouping
required data into small, self-validating immutable value objects.

For example, a future rotation-specific parameter object can keep canonical radians
and optional source display metadata together:

```python
@dataclass(frozen=True, slots=True)
class RotationParameters:
    radians: float
    source_angle: AngleMetadata | None
```

A constructor or factory that accepts `RotationParameters` can validate its
relationship once, rather than forcing every compiler, runtime, and UI consumer to
recheck unrelated optional fields. The same technique applies to measurement
configuration, classical conditions, basis descriptors, backend requests,
breakpoints, and sampled versus exact result records.

This is not an argument for a gate-class hierarchy. It is an argument for keeping
concepts that must remain consistent in the same validated object.

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
`AngleMetadata`, `ProgramId`, `SourceNodeId`, `SnapshotOperationId`,
`IrOperationId`, `SourceRange`, and `SourceRef`.

Future language work should introduce value objects where a bare integer or string
would lose meaning, including:

- `QubitRef` and `RegisterRef` for named registers;
- `Basis` and basis expressions;
- `MeasurementKey` and classical conditions;
- `Probability`, `ShotCount`, and backend identifiers; and
- execution occurrence and breakpoint identities.

For example, named registers should preserve author intent before lowering to a
physical or simulator index:

```python
@dataclass(frozen=True, slots=True)
class QubitRef:
    register: RegisterId
    index: int
```

A value object validates itself, compares by value, remains immutable, and has a
stable serialized form. Do not create one merely to wrap every primitive; create
one when the name carries a domain invariant or prevents an ambiguous boundary.

## Identity across layers

Layers link through durable identifiers, never Python object identity. The current
identity chain is scoped by `ProgramId` and can be viewed as:

```text
SourceNodeId (optional durable editor identity)
    -> SnapshotOperationId (one compiled source snapshot)
    -> IrOperationId (one semantic operation)
    -> trace step index (one execution occurrence today)
    -> TraceStepInspection
    -> TraceStepViewModel
```

`SourceNodeId` must survive source editing when supplied by an editor. Snapshot
operation IDs are deterministic only inside a compiled snapshot. IR operation IDs
distinguish lowered or generated semantic operations. Trace steps preserve an
ordered occurrence of an IR operation during one execution.

A future `OperationLink` value object may centralize these relationships for
source navigation, persistent breakpoints, compiler provenance, remote result
reconciliation, tutorial checkpoints, and Studio synchronization:

```python
@dataclass(frozen=True, slots=True)
class OperationLink:
    program_id: ProgramId
    source_node_id: SourceNodeId | None
    snapshot_operation_id: SnapshotOperationId | None
    ir_operation_id: IrOperationId
    execution_occurrence_id: ExecutionOccurrenceId | None
```

This is a future extension. It must not replace existing identifiers until it can
represent every current relationship without information loss.

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
include validation, name resolution, type checking, angle normalization, function
expansion, basis lowering, decomposition, routing, resource estimation, and
backend lowering.

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

## Native-language application

The native `.ari` language must keep author syntax separate from semantic meaning
and compiled IR. A parser node should preserve spelling and source range; a
resolved node should preserve symbol binding; a typed node should establish domain
meaning; and only then should Daidalon lower it to IR.

```text
Syntax node -> resolved semantic node -> typed semantic node -> IR operation
```

For example, `rx data[0], 190deg` retains `190deg` in syntax, becomes an angle in
the typed model, and lowers to canonical radians plus source metadata in IR.
Parser nodes must not double as `CircuitIR` operations.

This supports the next language milestones: native syntax and source AST, named
registers and explicit basis semantics, then parser, name-resolution, and lowering
pipelines.
