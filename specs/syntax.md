# Native Ariadion syntax and source AST — draft 0

`ariadion-syntax` defines immutable source contracts for native `.ari` programs.
It deliberately does **not** include a lexer, parser, name resolver, type checker,
or IR lowering yet. The first contract freezes written syntax and source identity
before parser behavior or semantic rules become public.

## Native grammar

The grammar is expressed in EBNF. Newlines separate declarations and statements;
blank lines are ignored by a future lexer/parser.

```text
program             = "program" , identifier , newline ,
                      { newline } ,
                      { qubit-register-declaration , newline , { newline } } ,
                      { statement , newline , { newline } } ;

qubit-register-declaration
                    = "qubits" , identifier , "[" , integer-literal , "]" ;

statement           = single-qubit-gate
                    | controlled-gate
                    | rotation
                    | measurement ;

single-qubit-gate   = ( "x" | "h" | "z" ) , qubit-reference ;
controlled-gate     = "cx" , qubit-reference , "," , qubit-reference ;
rotation            = ( "rx" | "ry" | "rz" ) , qubit-reference , "," ,
                      angle-literal ;
measurement         = "measure" , qubit-reference , "in" , basis-expression ,
                      "->" , identifier ;

qubit-reference     = identifier , "[" , integer-literal , "]" ;
basis-expression    = identifier ;
angle-literal       = signed-decimal , ( "deg" | "rad" | "turns" ) ;
identifier          = letter-or-underscore , { letter | digit | "_" } ;
integer-literal     = digit , { digit } ;
signed-decimal      = [ "+" | "-" ] , integer-literal ,
                      [ "." , integer-literal ] ;
```

The following are valid written programs:

```text
program bell

qubits data[2]

h data[0]
cx data[0], data[1]
measure data[0] in z -> result
```

```text
program rotations

qubits data[1]

ry data[0], 90deg
rz data[0], 0.5turns
```

The grammar permits zero or more register declarations. It keeps declarations
before executable statements structurally, but it does not require quantum storage
or decide whether declarations form a valid quantum layout. A source reference such
as `data[0]` remains symbolic and is never flattened into a simulator index by the
syntax layer.

## Source AST

`ProgramSyntax` is the immutable root. It keeps ordered `declarations` separate
from ordered executable `statements`, so declarations cannot appear after a gate
or measurement. Schema version $3$ accepts a sequence of
`QubitRegisterDeclaration` values, including an empty sequence, because the source
AST records syntax rather than semantic validity.

Statements are `GateStatement`, `RotationStatement`, and
`MeasurementStatement`. A `QubitRegisterDeclaration` contains an author-written
register `name` and `size`; a `QubitReference` contains its symbolic `register`
and `index`. `GateStatement` represents the currently supported non-rotation
primitives (`x`, `h`, `z`, and `cx`), while `RotationStatement` retains a
`RotationAxis`, `QubitReference`, and `AngleLiteral`. `MeasurementStatement`
contains a `QubitReference`, a `BasisExpression`, and a result-key `Identifier`.

`BasisExpression` currently contains an `Identifier` such as `x`, `y`, or `z`.
It is deliberately not an IR enum: later syntax can introduce named bases such as
`basis diagonal = ...` without replacing the source expression model.

Every AST node contains a `SyntaxLocation`, which combines:

- a complete one-based `SourceRange`; and
- a required snapshot-scoped `SyntaxNodeId`; and
- an optional durable `SourceNodeId` supplied by an editor.

`SyntaxNodeId` is unique within a `ProgramSyntax` and can be assigned by an
ordinary CLI parser for one document snapshot. It is not claimed to survive edits.
`SourceNodeId`, when present, must also be unique and is the only identity intended
to persist editor selection, breakpoints, or tutorial state across edits. Neither
identity relies on Python object identity.

`Identifier`, `IntegerLiteral`, and `AngleLiteral` are source values rather than
semantic values. An `AngleLiteral` preserves spelling such as `90deg` or
`0.5turns`, its exact `numeric_text`, and its unit suffix. It does not convert to
`float`, calculate canonical radians, or decide numeric representability; typed
semantic analysis will make those decisions later using an explicit numeric policy.

## Deliberately deferred semantic validation

The syntax AST accepts grammatically valid text even when later layers will reject
its meaning. For example, this is a valid source AST:

```text
qubits data[2]
measure missing[7] in banana -> result
```

Later name resolution and typed semantic validation determine that `missing` is an
unknown register, `7` is out of range when a register is known, and `banana` is an
unknown basis. They also own duplicate register-name checks, positive register
size checks, and whether a program requires quantum storage. The syntax package
must not flatten references, impose those semantic rules, or import IR to do so.

## Tokens and diagnostics

`TokenKind` and `Token` define the lexical vocabulary and preserve original token
spelling plus a complete source range. They are contracts for a future lexer, not
a parser implementation. The future lexer owns fixed-token spelling validation and
reserved-word classification. Token constructors intentionally preserve the spelling
provided by that lexer; they validate only token shape, EOF spelling, and location.

`SyntaxDiagnostic` is independent from Daidalon diagnostics. A lexer or parser can
report an `S...` source error with a source range before name resolution, type
checking, or IR lowering exists. Semantic diagnostics will remain a later layer.

## Serialization

AST values, tokens, source locations, and syntax diagnostics provide deterministic
`to_dict()` and canonical `to_json()` output. `ProgramSyntax` documents its
`schema_version` as $3$. Version $3$ replaces the single fixed-width declaration
with ordered named register declarations and adds a basis expression to
measurements. Version $2$ remains the prior serialized shape; clients must not
interpret a version $3$ document as version $2$. AST fixtures and frontend
documents therefore evolve independently from execution traces and IR.

## Boundary

The intended path is:

```text
written syntax
    -> immutable source AST
    -> resolved semantic model
    -> typed semantic model
    -> Daidalon lowering
    -> CircuitIR
```

Parser nodes must never double as `CircuitIR` operations. Syntax preserves author
spelling and source location; later semantic layers establish names, types, and
canonical values; IR captures provider-neutral compiled meaning.
