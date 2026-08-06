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

This document defines the target public language; the current runtime still
executes the width-based Python builder described below. `Program(width)` and its
integer-target operations are compatibility and migration mechanisms, not the
future source-language model. A hand-built `LogicalProgram` now proves the first
logical-value lowering slice, but AST capture and public quantum-function lowering
remain future work.

## Python-compatible quantum functions

The first executable frontend must use valid Python and Python's parser. This is a
target contract, not an implemented API yet:

```python
from ariadion import Bit, Qubit, basis, cx, h, quantum


@quantum(basis=basis.z)
def bell() -> tuple[Bit, Bit]:
   left = Qubit()
   right = Qubit()

   h(left)
   cx(left, right)

   return left, right
```

`Qubit` is the public source-level managed quantum-value type. A source-level
`Qubit` is logical by definition; it has no second construction mode, wrapper, or
flag. `left` and `right` are neither simulator indexes nor hardware addresses, and
the decorator captures supported code for compilation rather than executing quantum
operations as ordinary Python calls.

Each `Qubit()` call creates a distinct managed value with an internal
`LogicalQubitId` before allocation. Assignment aliases that value; it never clones
quantum state. In the example, `left` and `right` have overlapping lifetimes, so
Daidalon will eventually infer a peak allocation of two slots even though neither
source value contains a target, index, or address.

The `tuple[Bit, Bit]` return annotation requires two ordered classical result
values. Returning the two `Qubit` values creates visible compiler-inserted terminal
observations in the function's declared `basis.z` policy. Each observation produces
a distinct `ClassicalBitId`; compiler artifacts retain its result identity, basis,
reason, and output order. Source code does not need terminal `measure()` calls.
The compiler lowers the simultaneously live values to dense targets in allocated
`CircuitIR`, while preserving result IDs separately from operation IDs and Python
variable names.

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

Quantum function parameters receive logical values without knowing a global qubit
count. Returning a quantum value remains a quantum return, not an observation:

```python
@quantum
def prepare_plus() -> Qubit:
   value = Qubit()  # Managed logical value.
   h(value)
   return value
```

No observation is inserted for `prepare_plus()` because its return type preserves a
quantum value across the function boundary. Quantum parameters bind managed values
rather than physical slots. A return value may be a classical observation result or
a quantum value whose lifetime escapes the function; neither parameter nor return
type exposes simulator or hardware indexes.

The semantic model will define ownership, aliasing, escaping values, reset, and
measurement consumption before allocation is implemented. Until then, no frontend
may imply that a Python assignment copies a quantum state or silently changes
quantum ownership. Measurement produces a classical result value; the precise
ownership effect on the measured logical value must be explicit in the later
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
the corresponding `ClassicalBitValue` and a flat, deterministic tuple of output
identities. Classical outputs must reference declared produced values; a quantum
output remains quantum and does not cause an observation. Every declared classical
value has exactly one observation producer, whether or not it is a public output.
Reasons distinguish an explicit `observe(...)` call from an inferred classical
return, classical
assignment, branch-condition, or program-output boundary. This lets compiler
artifacts and execution traces explain an observation without pretending it was a
user-written low-level `MEASURE` operation.

## Logical quantum values and managed resources

Each `Qubit()` creation receives a logical identity. Resolved quantum operations
target those identities, and a future lifetime analysis will determine the peak
simultaneously live set. The current hand-built logical slice instead allocates one
dense slot per declared logical value in declaration order, then lowers to
`CircuitIR`.

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
`ReadoutPlan` preserves every allocated observation and the original flat output
order. Exact execution computes one `ExactClassicalDistribution` across the ordered
classical outputs, rather than pretending that separate 50/50 marginal records
express a correlated result. For Bell outputs in order `(left_result, right_result)`,
the distribution is $00 \mapsto 0.5$, $01 \mapsto 0$, $10 \mapsto 0$, and
$11 \mapsto 0.5$.

Exact simulation may calculate a terminal observation distribution without
sampling or mutating the retained analytical state. This is not physical
post-measurement state evolution. Sampled collapse and mid-circuit feedback are
separate execution capabilities. The exact engine rejects a gate after an
observation with `A202`; future sampled execution must define shots, seeds,
individual outcomes, collapse, feedback, reset, and trace granularity.

## Current compatibility surface

The working builder currently appends operations to a preallocated program:

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

Rotations require an explicit unit-bearing `Angle`. The valid-Python frontend uses
`deg()`, `rad()`, or `turns()`:

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
`RY`, or `RZ` members. A future `LogicalRotationOperation` must use a unit-bearing
semantic angle before lowering into canonical allocated-IR radians; it must not use
an untyped parameter dictionary.

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

The public namespace is `basis.x`, `basis.y`, `basis.z`, and
`basis.named("custom-name")`; lower-case basis constants are not exported because
they would collide with gate functions such as `x(target)` and `z(target)`. A
quantum function may later establish a default basis with
`@quantum(basis=basis.z)`. Whatever additional syntax is adopted, the resolved
semantic model must retain the selected basis and Daidalon must lower any basis
change explicitly. The future frontend's default terminal-observation basis is
`basis.z` only when the language contract declares that policy; backends must not
infer measurement bases.

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
remain classical unless explicitly supported. A quantum function may call another
resolved quantum function or an explicitly supported classical subroutine, subject
to later capture and control-flow rules. Imports, classes, exceptions, collections,
and ordinary calls retain their normal Python behavior outside an explicit quantum
boundary.

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

The frontend uses Python's grammar for ordinary Python. Valid-Python quantum
constructs can parse directly through Python's AST. When Ariadion-specific syntax
is present, extension-aware tokenization or source transformation runs before
Python AST parsing and supplies extension nodes alongside the resulting Python AST.
Transformation must preserve a mapping to original source spans; it must never
silently redefine unmarked Python syntax.

Python syntax errors remain Python syntax errors. Ariadion extension, capture,
resolution, type, ownership, and resource failures use source-linked diagnostics
with exact original locations. `SyntaxDiagnostic` remains independent from
semantic compiler diagnostics.

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
`LogicalQubitId -> ClassicalBitId -> ordered classical output`.

## Source-model and IR boundary

The source model must not contain a physical qubit index or a required global
width. It establishes written quantum constructs and logical-value relationships;
the resolved semantic model establishes bindings, types, ownership, aliases,
function calls, basis values, and lifetimes. Daidalon then creates an allocation
plan and lowers the result into integer-target `CircuitIR`.

```text
Python-compatible Ariadion source
   -> Python AST and Ariadion extension nodes
   -> resolved quantum values and effects
   -> typed ownership and observation semantics
   -> logical operation schedule
   -> reliability analysis
   -> protection and allocation plan
   -> allocated CircuitIR
   -> simulator or hardware backend
```

The extension-source contracts are specified separately in
[`specs/syntax.md`](syntax.md). They retain exact spelling, source ranges, and
identity without trying to replace Python's AST.

## Research references

The evidence and limitations behind the future noise, simulation, and protection
interfaces are recorded in [noise-modeling research](../docs/research/noise-modeling.md)
and [fault-tolerance and resource-planning research](../docs/research/fault-tolerance-and-resource-planning.md).
Those records cite primary papers and official technical documentation consulted on
2026-08-06.
