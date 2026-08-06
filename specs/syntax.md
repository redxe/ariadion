# Ariadion Python-extension syntax and source contracts — draft 1

`ariadion-syntax` defines immutable, source-preserving contracts for Ariadion
extensions embedded in Python-compatible source. It does not replace Python's AST,
include a standalone `.ari` lexer or parser, resolve names, type check, allocate
resources, or lower to IR.

## Public direction

The future language is a managed Python quantum extension. A public source program
does not begin with `program name` or `qubits data[2]`, and it does not address a
qubit by a source-level integer. Those forms are not requirements for the future
language grammar and must not drive a standalone parser implementation.

The first executable frontend will use valid Python; this is the target surface,
not an implemented API yet:

```python
from ariadion import Bit, Qubit, cx, h, quantum, z


@quantum(basis=z)
def bell() -> tuple[Bit, Bit]:
    left = Qubit()
    right = Qubit()
    h(left)
    cx(left, right)
    return left, right
```

`left` and `right` are logical quantum values. Resource analysis and allocation
later decide their lifetimes, reuse, dense IR targets, simulator width, and hardware
layout. The declared classical return type creates terminal observations; explicit
`observe(...)` remains available when an algorithm needs an earlier observation.
Source `Qubit` values do not expose integer targets or a representation choice:
`LogicalQubitId` is their pre-allocation semantic identity, an
`AllocatedQubitSlot` is a compiler-selected target, and a `ProtectedRealization`
is an encoded physical realization rather than a public value type.

## Extension-aware frontend

Python owns parsing of ordinary Python. An extension-aware tokenizer or source
transformation recognizes only explicit Ariadion constructs, preserves a mapping to
the original source, and then supplies Python AST facts plus Ariadion extension
nodes to semantic analysis. Unmarked Python must never acquire quantum meaning.

Future Ariadion sugar can include unit-bearing angle literals such as `190deg` and
basis-aware `observe(...)` syntax. Such forms are justified only after they lower
into the same semantic model proven by the valid-Python frontend. A file extension
such as `.ari` does not imply a second language grammar; it may hold
Python-compatible Ariadion source when file loading and Studio support need it.
Ordinary `.py` remains classical by default unless `@quantum` opts in; future `.ari`
files infer effects by default, while `@classical` constrains a region to remain
classical. No `.ari` parser is implemented by this contract.

## Future source AST

The extension AST models only Ariadion concepts; it deliberately does not recreate
Python's nodes. Intended node families include:

- `QuantumFunctionSyntax` for an explicitly marked quantum function;
- `QuantumValueBindingSyntax` for a logical-value creation or binding;
- `QuantumOperationSyntax` for an operation over logical values;
- `MeasurementExpressionSyntax` for an explicit value-producing observation; and
- `BasisExpression` and `AngleLiteral` for exact author-written domain values.

These nodes retain exact spelling, complete source ranges, a required
snapshot-scoped `SyntaxNodeId`, and an optional durable editor `SourceNodeId`.
They describe logical values and measurement intent, never physical indexes or a
required global allocation width.

## Existing schema v3 compatibility

The current immutable `ProgramSyntax` document model remains available at schema
version $3$. Its `QubitRegisterDeclaration`, register/index `QubitReference`,
gate statements, rotations, and basis-aware measurements preserve source data for
existing frontend documents and tests. It is not a commitment to the future public
language grammar, and no standalone lexer or parser will be built around it.

`BasisExpression`, `AngleLiteral`, `Identifier`, `IntegerLiteral`, and
`SyntaxLocation` remain useful source-value contracts. In particular,
`AngleLiteral` preserves exact spelling such as `90deg` or `0.5turns`, its
`numeric_text`, and unit suffix without converting to `float` or canonical radians.
`BasisExpression` remains an author-written value rather than an IR enum.

The v3 register declaration and indexed reference shapes are transitional source
data. Future extension nodes use bindings to logical quantum values instead of a
required explicit register size or global source index. Existing serialized v3
documents must remain interpretable as v3 until a deliberate migration is defined.

## Source identities and semantic boundary

Every AST node has a `SyntaxLocation` containing a complete one-based
`SourceRange`, a required snapshot-scoped `SyntaxNodeId`, and an optional durable
editor `SourceNodeId`. A `SyntaxNodeId` is unique within one parsed document
snapshot and does not survive edits. A supplied `SourceNodeId` is separately unique
and is the only identity intended to persist selection, breakpoints, or tutorial
state across edits. Neither identity relies on Python object identity.

Source contracts preserve what the author wrote; later layers establish bindings,
types, quantum ownership, aliases, basis meanings, function calls, lifetimes, and
inferred observation boundaries, scheduling, reliability analysis, and allocation.
In particular, syntax must not validate a physical target range, infer a basis,
create an allocation width, choose protection, or import IR to decide those
meanings.

## Tokens and diagnostics

`TokenKind` and `Token` define the lexical vocabulary and preserve original token
spelling plus a complete source range. They support future extension-aware
tokenization or source transformation; they do not require a standalone `.ari`
lexer or parser. The extension-aware frontend owns fixed-token spelling validation
and reserved-word classification. Token constructors intentionally preserve the
spelling supplied by that frontend; they validate only token shape, EOF spelling,
and location.

`SyntaxDiagnostic` is independent from Daidalon diagnostics. The extension-aware
frontend can report an `S...` source error with an original source range before
name resolution, type checking, or IR lowering exists. Semantic diagnostics remain
a later layer.

## Serialization

AST values, tokens, source locations, and syntax diagnostics provide deterministic
`to_dict()` and canonical `to_json()` output. `ProgramSyntax` remains schema
version $3$ for existing serialized documents. Version $3$ is a compatibility
shape with named-register declarations and basis-aware measurements; clients must
not interpret it as version $2$, nor treat it as the permanent public language
grammar. Future Python-extension frontend documents need their own explicit schema
version and migration path.

## Boundary

The intended path is:

```text
Python-compatible source
    -> extension-aware transformation and Python AST
    -> immutable Ariadion extension nodes
    -> resolved quantum values and effects
    -> typed ownership and observation semantics
    -> logical operation schedule
    -> reliability analysis
    -> protection and allocation plan
    -> allocated CircuitIR
```

Extension nodes must never double as `CircuitIR` operations. Syntax preserves
author spelling and source location; later semantic layers establish logical-value
bindings, types, ownership, bases, and canonical values; allocation creates dense
integer targets; IR captures provider-neutral compiled meaning.

## Research references

The evidence for the future noise, scheduling, and protection boundary is recorded
in [noise-modeling research](../docs/research/noise-modeling.md) and
[fault-tolerance and resource-planning research](../docs/research/fault-tolerance-and-resource-planning.md).
Those records cite primary papers and official technical documentation consulted on
2026-08-06.
