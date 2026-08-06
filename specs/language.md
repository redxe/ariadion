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
future source-language model. They remain supported until logical-value lowering
proves an equivalent vertical slice.

## Python-compatible quantum functions

The first executable frontend must use valid Python and Python's parser. This is a
target contract, not an implemented API yet:

```python
from ariadion import Bit, Qubit, cx, h, quantum


@quantum(basis=z)
def bell() -> tuple[Bit, Bit]:
   left = Qubit()
   right = Qubit()

   h(left)
   cx(left, right)

   return left, right
```

`Qubit` is the public logical quantum-value type. “Logical qubit” is compiler
terminology, not a second user-facing wrapper or construction mode. `left` and
`right` are neither simulator indexes nor hardware addresses. The decorator
captures supported code for compilation; it must not execute quantum operations as
ordinary Python calls.

`Qubit()` is the only public construction mode. There is no lowercase factory,
logical-mode flag, or public logical-value wrapper; physical locations, simulator
indexes, hardware indexes, and allocated slots are compiler concepts only.

The `tuple[Bit, Bit]` return annotation requires classical result values. Returning
the two `Qubit` values across that boundary creates terminal observations in the
function basis policy. It does not require source-level terminal `measure()` calls.
The compiler will later infer that the values are simultaneously live and allocate
two dense IR targets for the existing `CircuitIR`.

Quantum function parameters receive logical values without knowing a global qubit
count. Returning a quantum value remains a quantum return, not an observation:

```python
@quantum
def prepare_plus() -> Qubit:
   value = Qubit()  # Managed logical value.
   h(value)
   return value
```

Quantum parameters bind logical values rather than physical slots. A return value
may be a classical measurement result or, when later ownership rules permit it, a
logical quantum value whose lifetime escapes the function. Neither parameter nor
return types expose simulator or hardware indexes.

The semantic model will define ownership, aliasing, escaping values, reset, and
measurement consumption before allocation is implemented. Until then, no frontend
may imply that a Python assignment copies a quantum state or silently changes
quantum ownership. Measurement produces a classical result value; the precise
ownership effect on the measured logical value must be explicit in the later
semantic contract.

The initial conversion policy is:

```text
Qubit -> Qubit       no observation
Qubit -> Bit         observation boundary
Qubit -> bool        semantic diagnostic
Bit -> bool          ordinary classical conversion
```

In particular, `if q:` for a `Qubit` is rejected initially. Ariadion must not
silently insert a mid-circuit measurement through ordinary Python truth testing.

## Logical quantum values and managed resources

Each `Qubit()` creation receives a logical identity. Resolved quantum operations
target those identities, and lifetime analysis determines the peak simultaneously
live set. Daidalon then allocates dense integer targets for `CircuitIR`.

```text
logical values and lifetimes
    -> allocation plan
    -> allocated CircuitIR.qubit_count and integer targets
```

The first allocation policy may use one slot per distinct live logical value. Later
policies can reuse a slot after a value's lifetime ends, introduce ancillas, insert
resets, route for hardware topology, and report provider-specific requirements.
The compiler must expose facts such as logical values created, peak live values,
allocated simulator qubits, and hardware qubits required. A future annotation such
as `@quantum(max_qubits=12)` is a resource contract or hint, not manual allocation.

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

## Basis values and measurement intent

A basis is a typed domain concept rather than a backend default. Explicit
measurement remains available when observation timing changes algorithm meaning:

```python
result = measure(target, basis=x)
```

Use explicit measurement for mid-circuit feedback, post-selection, exact timing,
basis-sensitive steps, reset and reuse, error-correction syndromes, or partial
observation of an entangled system. Returning a `Qubit` where a declared `Bit` is
required is instead a terminal observation boundary.

The precise spelling of basis values is not frozen. A quantum function may later
establish a default basis with `@quantum(basis=z)`, a scoped context such as
`with basis(x):`, or a custom basis-producing function marked with `@basis`.
Whatever syntax is adopted, the resolved semantic model must retain the selected
basis and Daidalon must lower any basis change explicitly. Backends must not infer
measurement bases.

## Classical and quantum call boundaries

Ordinary Python functions are classical by default. They cannot implicitly create,
operate on, or capture logical quantum values. A quantum function may call another
resolved quantum function or an explicitly supported classical subroutine, subject
to later capture and control-flow rules. Imports, classes, exceptions, collections,
and ordinary function calls retain Python behavior outside the explicit quantum
boundary.

A future `@classical` marker may document classical subroutines callable from a
quantum workflow, but it is not required to preserve ordinary Python semantics.
The semantic model, rather than a decorator name alone, will determine which values
cross a classical/quantum call boundary and whether those values are legal.

## Effect defaults and constraints

The target source-effect model has two defaults:

```text
.py file:
   classical Python by default; @quantum opts into quantum compilation

.ari file:
   quantum-effect inference by default; @classical explicitly forces classical execution
```

This is a language target only; `.ari` parsing is not implemented. Internally,
semantic analysis reserves `FunctionEffect.CLASSICAL`, `FunctionEffect.QUANTUM`,
and `FunctionEffect.HYBRID`. Source annotations act as constraints that the future
analyzer checks against operations and value flow rather than as a substitute for
effect inference.

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

The following identity behavior describes the current width-based builder
compatibility surface. A logical-value frontend will preserve the same
snapshot-versus-durable distinction without requiring a `Program(width)` source API.

Each `Program` has a `ProgramId` that scopes source and IR artifacts. The default
is a process-local snapshot ID of the form `snapshot:<creation-index>:<name>`, so
two ordinary default-named programs do not collide. Frontends should pass a stable
document or project identity through `Program(..., program_id="examples/bell.py")`
when source artifacts leave the current process.

Every builder-created operation receives a `SnapshotOperationId` of the form
`<program-id>:operation:<insertion-index>`. It is deterministic within one program
snapshot and suitable for a compiled trace, but it is not durable across edits:
inserting an earlier operation renumbers later snapshot IDs.

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
`program_id`, `snapshot_operation_id`, `source_node_id`, and `source_range` through
their immutable source reference. The compatibility `source_id` property resolves
to the durable node ID when present and otherwise to the snapshot operation ID.
Program-wide diagnostics may have no source reference; their messages remain useful
without a file or position.

`SyntaxNodeId` identifies one parsed source snapshot and `SourceNodeId`, when
supplied by an editor, identifies a durable source element across edits. Builder
`SnapshotOperationId` values remain compatibility identities for the existing
width-based API; future logical operations require their own source and semantic
identities before allocation generates IR-operation IDs.

## Source-model and IR boundary

The source model must not contain a physical qubit index or a required global
width. It establishes written quantum constructs and logical-value relationships;
the resolved semantic model establishes bindings, types, ownership, aliases,
function calls, basis values, and lifetimes. Daidalon then creates an allocation
plan and lowers the result into integer-target `CircuitIR`.

```text
Python-compatible Ariadion source
    -> Python AST plus Ariadion extension nodes
    -> resolved quantum semantic model
    -> lifetime and resource analysis
    -> allocated provider-neutral CircuitIR
```

The extension-source contracts are specified separately in
[`specs/syntax.md`](syntax.md). They retain exact spelling, source ranges, and
identity without trying to replace Python's AST.
