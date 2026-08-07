# Ariadion language model — draft 1

Ariadion is a managed quantum extension of Python. Programmers express logical
quantum values, algorithms, relationships, and measurement intent. Ariadion owns
resource allocation, lifetime analysis, reuse, layout, routing, decomposition,
and the eventual mapping to simulator or hardware qubits.

## Language charter

1. **Python compatibility:** ordinary valid Python retains ordinary Python meaning
   unless code explicitly enters an Ariadion quantum construct.
2. **Logical values, not addresses:** source programs manipulate logical quantum
   values. Physical qubit indexes and an allocated width are compiler results, not
   source-level inputs.
3. **Explicit quantum boundary:** `@quantum` marks code captured as a quantum
   program. Ordinary functions, imports, classes, exceptions, and collections
   remain classical Python by default.
4. **Visible managed resources:** allocation is automatic but observable through
   compiler artifacts, diagnostics, and debugger views.
5. **Layered meaning:** source spelling, resolved quantum semantics, resource
   allocation, and provider-neutral IR remain distinct models.
6. **No backend guesses:** units, bases, measurement intent, and resource
   constraints are explicit source or semantic facts before lowering.

## Status and compatibility

The first valid-Python `@quantum` frontend is implemented. It captures a narrow,
deliberately safe subset of a decorated function into `LogicalProgram`; it does
not add function composition, bindings, classical computation, control flow, or a
native `.ari` parser. `Program(width)` and its integer-target operations remain
compatibility and migration mechanisms rather than the managed source-language
model.

## Python-compatible quantum functions

Ariadion reads the Python AST of a quantum function. It does not execute the
function body to construct the program. The implemented frontend uses valid Python
and Python's parser:

```python
from ariadion import Bit, Qubit, basis, cx, h, quantum, run


@quantum(basis=basis.z)
def bell() -> tuple[Bit, Bit]:
   left = Qubit()
   right = Qubit()

   h(left)
   cx(left, right)

   return left, right


result = run(bell)
```

`Qubit` is the public source-level managed quantum-value type. A source-level
`Qubit` is logical by definition; it has no second construction mode, wrapper, or
flag. `left` and `right` are neither simulator indexes nor hardware addresses. The
decorator resolves only supported AST nodes for compilation; it never executes the
function body, `Qubit()` declarations, gate markers, or angle helpers as ordinary
Python calls.

Each captured `Qubit()` declaration creates a distinct semantic value with an
internal `LogicalQubitId` before allocation. Assignment aliases that value; it
never clones quantum state. In the example, `left` and `right` have overlapping
lifetimes, so the current declaration-order allocation produces two slots even
though neither source value contains a target, index, or address.

The `tuple[Bit, Bit]` return annotation requires two structured classical result
leaves. Returning the two `Qubit` values creates visible compiler-inserted terminal
observations in the function's declared `basis.z` policy. Each observation produces
a distinct `ClassicalBitId`; compiler artifacts retain its result identity, basis,
reason, and position inside the semantic return tree. Source code does not need
terminal `measure()` calls. The compiler lowers the simultaneously live values to
dense targets in allocated `CircuitIR`, while preserving result IDs separately from
operation IDs and Python variable names.

The terminology boundary is deliberate:

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

`LogicalQubit` is not a public type and must not name a QEC realization, because it
would collide with the source-semantic meaning. See the object-model guide for the
cross-layer identity rules.

The implemented subset accepts flat positional parameters annotated with `Qubit`.
Capture declares each as a `QuantumParameter` and a corresponding logical value
without knowing a global qubit count. Returning a quantum value remains a quantum
return, not an observation:

Annotations are read from their AST nodes rather than evaluated. The initial forms
are exactly `Qubit`, `Bit`, `None`, and nested built-in `tuple[...]`; custom aliases
and `typing` forms are intentionally rejected.

```python
@quantum
def prepare_plus() -> Qubit:
   value = Qubit()  # Managed logical value.
   h(value)
   return value
```

For example, this function captures successfully but cannot run independently:

```python
from ariadion import Qubit, deg, quantum, rx


@quantum
def rotate_input(target: Qubit) -> Qubit:
   rx(target, deg(190))
   return target
```

`run(rotate_input)` raises `UnboundQuantumParameterError` with code `P113`. This
protects an input from being silently treated as a newly allocated $|0\rangle$
value. Function composition and explicit input binding are later work.

No observation is inserted for `prepare_plus()` because its return type preserves a
quantum value across the function boundary. Quantum parameters bind managed values
rather than physical slots. A return value may be a classical observation result or
a quantum value whose lifetime escapes the function; neither parameter nor return
type exposes simulator or hardware indexes.

The semantic model will later define ownership, escaping values, reset, and
measurement consumption. The current frontend already preserves source-level alias
identity, but it must not imply that an assignment copies a quantum state or
silently changes quantum ownership. Measurement produces a classical result value;
the precise ownership effect on the measured logical value remains a later
semantic contract.

The initial conversion policy is:

```text
Qubit -> Qubit
   Preserve the quantum value.

Qubit -> Bit
   Insert an observable semantic boundary.

Qubit -> bool
   Reject with a semantic diagnostic.

Bit -> bool
   Ordinary classical conversion.
```

In particular, `if q:` for a `Qubit` is rejected initially. Ariadion must not
silently insert a mid-circuit measurement through ordinary Python truth testing.

The resolved semantic `Observation` records its own `LogicalOperationId`, the
observed `LogicalQubitId`, a produced `ClassicalBitId`, selected `Basis`, an
`ObservationReason`, and an optional source reference. A `LogicalProgram` declares
the corresponding `ObservationResultValue`. This intentionally names only
observation-origin classical values: future hybrid functions will also model
parameters, literals, classical computation, and backend metadata separately.
Every declared observation result has exactly one observation producer, whether or
not it is returned. Reasons distinguish an explicit `observe(...)` call from an
inferred classical return, classical assignment, branch-condition, or
program-output boundary. This lets compiler artifacts and execution traces explain
an observation without pretending it was a user-written low-level `MEASURE`
operation.

## Logical quantum values and managed resources

Each `Qubit()` creation receives a logical identity. Resolved quantum operations
target those identities, and a future lifetime analysis will determine the peak
simultaneously live set. The current captured and hand-built logical slice instead
allocates one dense slot per declared logical value in declaration order, then
lowers to `CircuitIR`.

```text
logical values and lifetimes
   -> logical operation schedule
   -> reliability analysis
   -> protection and allocation plan
    -> allocated CircuitIR.qubit_count and integer targets
```

The current `dense-no-reuse-v1` `LogicalSlotAllocationPlan` uses one slot per
declared logical value, reports equal peak-live and allocated counts, and never
reuses a slot. It is an execution-slot artifact, not a physical or protected
hardware allocation: a later physical plan may map one source `Qubit` to many
hardware qubits. Later policies can reuse a slot after a value's lifetime ends,
introduce ancillas, insert resets, route for hardware topology, select a
`ProtectedRealization`, and report provider-specific requirements. The compiler
must expose facts such as logical values created, peak live values, allocated
simulator qubits, hardware qubits, and planning assumptions. A future annotation
such as `@quantum(max_qubits=12)` is a resource contract or hint, not manual
allocation.

## Classical outputs and exact terminal observations

The current logical execution slice supports only terminal Z-basis observations.
A function return is a structured semantic artifact, not merely an ordered list of
identifiers. Classical observation results and returned quantum values may coexist,
and their Python tuple structure is preserved independently of allocation or
measurement order.

`ReturnShape` supports only `NoneReturn` for a whole-function `None` return, a
tagged `ScalarReturn`, and recursively nested `TupleReturn` nodes. `NoReturn`
remains a compatibility alias for `NoneReturn`; it is not `typing.NoReturn` and
cannot occur inside a tuple. Every scalar leaf is a `ReturnValueRef` whose
`ReturnValueKind` is explicitly `classical_bit` or `quantum_value`. This tag
remains serialized even though the currently declared ID sets do not overlap, so
IDE clients never infer output type from identifier spelling. A one-element tuple
is a `TupleReturn` with one item, not a scalar return. Lists, mappings, arbitrary
objects, generators, and unions are not return contracts yet.

`ReadoutPlan` retains all allocated observations, including explicitly discarded
ones, plus the original `return_shape`. Its deterministic left-to-right traversal
produces separate classical and quantum leaf sequences. A returned `Qubit` is not
observed; it remains a handle into the retained state and can remain entangled with
other returned quantum values. It is not an extracted standalone state vector.

Exact execution computes one `ExactClassicalDistribution` only across the returned
classical leaves, rather than pretending that separate 50/50 marginals express a
correlated result. For Bell results in return order `(left_result, right_result)`,
the joint distribution is $00 \mapsto 0.5$, $01 \mapsto 0$, $10 \mapsto 0$, and
$11 \mapsto 0.5$. Per-observation exact probabilities are marginals. The complete
returned classical result is a separately calculated joint distribution.

Exact simulation may calculate a terminal observation distribution without
sampling or mutating the retained analytical state. This is not physical
post-measurement state evolution. Sampled collapse and mid-circuit feedback are
separate execution capabilities. The exact engine rejects a gate after an
observation with `A202`; future sampled execution must define shots, seeds,
individual outcomes, collapse, feedback, reset, and trace granularity.

## Current compatibility surface

The width-based builder remains a working compatibility API that appends operations
to a preallocated program:

```python
program = Program(2, name="bell")
program.h(0)
program.cx(0, 1)
```

It supports `x`, `h`, `z`, `rx`, `ry`, `rz`, `cx`, and `measure`. Integer targets
and the constructor width describe already allocated IR-like slots. New source
features must not extend this API as the long-term user model; the logical-handle
builder prototype is the next migration step.

## Angles and rotations

Rotations require an explicit unit-bearing `Angle`. The valid-Python frontend
captures only `deg()`, `rad()`, or `turns()` around one finite numeric literal:

```python
@quantum
def rotate(target: Qubit):
   rx(target, deg(190))
   ry(target, rad(2))
   rz(target, turns(0.25))
```

An `Angle` preserves its source value and unit while carrying a canonical-radians
semantic value. A later Ariadion extension literal such as `190deg` may preserve
its exact lexical text as an `AngleLiteral`, but it must lower into the same angle
semantic model. The compiler never guesses whether a bare numeric argument means
degrees, radians, or turns.

The current `LogicalGateOperation` deliberately contains no parameterless `RX`,
`RY`, or `RZ` members. `LogicalRotationOperation` instead owns one typed
`SemanticAngle` with source value, source unit, and validated canonical radians.
It is constructed from an explicit public `Angle` or the frontend's explicit
angle-call AST, never from an untyped bare numeric value. Daidalon lowers
`RotationAxis.X`, `.Y`, and `.Z` to allocated `RX`, `RY`, and `RZ` operations while
preserving both canonical radians and original display metadata.

The implemented frontend remains valid Python and does not execute a function to
discover its angle:

```python
from ariadion import Qubit, deg, quantum, rx


@quantum
def rotate(target: Qubit) -> Qubit:
   rx(target, deg(190))
   return target
```

AST capture converts `deg(190)` directly into a validated `SemanticAngle` and then
canonical allocated-IR radians, preserving the source unit and numeric value. Bare
numeric arguments and computed angle expressions are rejected with `P112`.

## Basis values and measurement intent

A basis is a typed domain concept rather than a backend default. Explicit
measurement remains available when observation timing changes algorithm meaning:

```python
result = observe(
     target,
   basis=basis.x,
     reset=True,
)
```

`observe` is the preferred future high-level spelling because it names the semantic
act. The low-level IR opcode may remain `MEASURE`, and the current
`Program.measure` builder method remains a compatibility API. Explicit observation
is required or useful for mid-circuit feedback, post-selection, exact timing,
syndrome extraction, partial observation of entangled values, reset and storage
reuse, and repeated sampling policies. Returning a `Qubit` where a declared `Bit`
is required is instead an inferred terminal observation boundary.

The public language namespace is `basis.x`, `basis.y`, `basis.z`, and
`basis.named("custom-name")`; lower-case basis constants are not exported because
they would collide with gate functions such as `x(target)` and `z(target)`. A
quantum function establishes its default inferred-return basis with
`@quantum(basis=basis.z)`; the default is `basis.z`. The captured semantic model
retains that selected basis. Current exact execution supports terminal Z-basis
observations only and diagnoses other bases during lowering; it never silently
changes or infers a measurement basis.

## Effect defaults and constraints

`FunctionEffect` classifies resolved functions as `CLASSICAL`, `QUANTUM`, or
`HYBRID`. These are semantic effects, not merely decorator names. The target
source-effect model has two defaults:

```text
.py file:
   classical Python by default; @quantum opts into quantum compilation

.ari file:
   quantum-effect inference by default; @classical constrains a function or region
   to classical behavior
```

`@classical` containing a quantum operation is an error. `@quantum` asserts that a
function is compilable as quantum code. An unannotated `.ari` function may be
inferred as classical, quantum, or hybrid. Imported ordinary Python functions
remain classical unless explicitly supported. The initial `@quantum` capture subset
does not support function composition, arbitrary classical calls, closures, or
mutable captured state; it accepts only the documented intrinsic marker calls.
Imports, classes, exceptions, collections, and ordinary calls retain their normal
Python behavior outside an explicit quantum boundary.

This is a language target only: `.ari` parsing is not implemented, and an
annotation is a constraint for future analysis rather than a replacement for effect
inference.

## Reliability intent and protection planning

Users express reliability intent rather than a physical allocation:

```python
@quantum(
     reliability=0.999999,
     protection="auto",
)
def algorithm():
     ...
```

The example requests a success target of $0.999999$, which maps to a maximum
failure budget of $10^{-6}$. A future compiler will use a `ReliabilityGoal`, chosen
noise profile, schedule, and backend assumptions to decide whether bare execution
is sufficient or whether a `ProtectionPlan` is feasible. Users do not select a
physical-qubit count or code distance unless they explicitly choose an advanced
override. This target API is not implemented in the current frontend.

## Source transformation, identity, and diagnostics

The implemented frontend uses Python's grammar for ordinary Python and captures the
valid-Python subset directly through Python's AST. Its `PythonSourceProvider`
boundary accepts inspected file source today and explicit in-memory source for a
future IDE buffer; it does not need to reread a saved file. The frontend derives
deterministic source operation IDs and complete one-based absolute ranges from that
source contract. When Ariadion-specific syntax is justified later,
extension-aware tokenization or source transformation must preserve a mapping to
original source spans and must never silently redefine unmarked Python syntax.

Python parser failures retain the parser's message and are surfaced as source-linked
frontend diagnostics. Ariadion extension, capture, resolution, type, ownership,
and resource failures likewise use exact original locations. The current frontend reports structured `P100`–
`P112` diagnostics for unavailable source, unsupported syntax, marker resolution,
argument shape, unresolved values, annotations, returns, and angle expressions;
`P113` rejects standalone execution with an unbound quantum parameter.
`SyntaxDiagnostic` remains independent from semantic compiler diagnostics.

The following identity behavior describes the width-based builder compatibility
surface and the neutral source-identity contract used by logical programs.

Each `Program` has a `ProgramId` that scopes source and IR artifacts. The default
is a process-local snapshot ID of the form `snapshot:<creation-index>:<name>`, so
two ordinary default-named programs do not collide. Frontends should pass a stable
document or project identity through `Program(..., program_id="examples/bell.py")`
when source artifacts leave the current process.

Every builder-created operation receives a `SnapshotOperationId` of the form
`<program-id>:operation:<insertion-index>`. It is deterministic within one program
snapshot and suitable for a compiled trace, but it is not durable across edits:
inserting an earlier operation renumbers later snapshot IDs.

Every source construct can instead have a neutral `SourceOperationId`. `SourceRef`
stores that canonical identity. For a builder-derived reference,
`snapshot_operation_id` remains an optional compatibility property; a semantic
program never invents a builder snapshot ID. Serialized source references retain
both `source_operation_id` and `snapshot_operation_id`; the latter is `null` for a
semantic reference without builder compatibility data.

A frontend that needs durable breakpoints, lesson checkpoints, or selected syntax
nodes must supply a `SourceNodeId` through `source_node_id`. Ariadion preserves it
separately from the snapshot ID; it does not attempt to infer durable identity from
Python line numbers. The prior `source_id` parameters remain compatibility aliases
for `program_id` and `source_node_id` respectively.

The builder captures the caller's file and one-based line number when Python makes
that information available. A frontend with richer location data can pass an
explicit `SourceRange` to any operation method, including one-based `column`,
`end_line`, and `end_column` values. Locations are optional; the operation ID is
always present for builder-created operations.

Compiler diagnostics retain their code and operation index, then expose
`program_id`, `source_operation_id`, optional `snapshot_operation_id`,
`source_node_id`, and `source_range` through their immutable source reference. The
`source_id` property resolves to the durable node ID when present and otherwise to
the source operation ID. Program-wide diagnostics may have no source reference;
their messages remain useful without a file or position.

`SyntaxNodeId` identifies one parsed source snapshot and `SourceNodeId`, when
supplied by an editor, identifies a durable source element across edits. Builder
`SnapshotOperationId` values remain compatibility identities for the existing
width-based API. Logical instructions use `LogicalOperationId`, including
observations, and each observation produces a `ClassicalBitId`, so the persistent
identity chain is
`SourceOperationId -> LogicalOperationId -> IrOperationId -> trace occurrence`
beside the value/result chain
`LogicalQubitId -> ClassicalBitId -> tagged structured return leaf`.

## Source-model and IR boundary

The source model must not contain a physical qubit index or a required global
width. It establishes written quantum constructs and logical-value relationships;
the resolved semantic model establishes bindings, types, ownership, aliases,
function calls, basis values, and lifetimes. Daidalon then creates an allocation
plan and lowers the result into integer-target `CircuitIR`.

```text
Python-compatible Ariadion source
   -> Python AST capture into LogicalProgram
   -> resolved logical values and typed return observations
   -> logical operation schedule
   -> reliability analysis
   -> protection and allocation plan
   -> allocated CircuitIR
   -> simulator or hardware backend
```

The `ariadion-syntax` extension-source contracts are specified separately in
[`specs/syntax.md`](syntax.md). They retain exact spelling, source ranges, and
identity without trying to replace Python's AST; they are not the runtime
valid-Python capture frontend.

## Research references

The evidence and limitations behind the future noise, simulation, and protection
interfaces are recorded in [noise-modeling research](../docs/research/noise-modeling.md)
and [fault-tolerance and resource-planning research](../docs/research/fault-tolerance-and-resource-planning.md).
Those records cite primary papers and official technical documentation consulted on
2026-08-06.
