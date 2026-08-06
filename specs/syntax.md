# Native Ariadion syntax and source AST — draft 0

`ariadion-syntax` defines immutable source contracts for native `.ari` programs.
It deliberately does **not** include a lexer, parser, name resolver, type checker,
or IR lowering yet. The first contract freezes written syntax and source identity
before parser behavior or semantic rules become public.

## Initial grammar

The grammar is expressed in EBNF. Newlines separate declarations and statements;
blank lines are ignored by a future lexer/parser.

```text
program             = "program" , identifier , newline ,
                      { newline } , qubit-declaration ,
                      { newline , statement } , { newline } ;

qubit-declaration   = "qubits" , integer-literal ;

statement           = single-qubit-gate
                    | controlled-gate
                    | rotation
                    | measurement ;

single-qubit-gate   = ( "x" | "h" | "z" ) , qubit-reference ;
controlled-gate     = "cx" , qubit-reference , "," , qubit-reference ;
rotation            = ( "rx" | "ry" | "rz" ) , qubit-reference , "," ,
                      angle-literal ;
measurement         = "measure" , qubit-reference , "->" , identifier ;

qubit-reference     = identifier , "[" , integer-literal , "]" ;
angle-literal       = signed-decimal , ( "deg" | "rad" | "turns" ) ;
identifier          = letter-or-underscore , { letter | digit | "_" } ;
integer-literal     = digit , { digit } ;
signed-decimal      = [ "+" | "-" ] , integer-literal ,
                      [ "." , integer-literal ] ;
```

The initial examples are therefore valid written programs:

```text
program bell

qubits 2

h q[0]
cx q[0], q[1]
measure q[0] -> result
```

```text
program rotations

qubits 1

ry q[0], 90deg
rz q[0], 0.5turns
```

The grammar recognizes a register name in every qubit reference but does not yet
assign register semantics. In this first source contract, `q[0]` remains a written
reference; it is not flattened into a simulator index.

## Source AST

`ProgramSyntax` is the immutable root. It keeps ordered `declarations` separate
from ordered executable `statements`, so declarations cannot appear after a gate
or measurement. Schema version $2$ currently requires exactly one
`QubitDeclaration`; the separate declaration sequence will grow when named
register declarations are introduced.

Statements are `GateStatement`, `RotationStatement`, and
`MeasurementStatement`. `GateStatement` represents the currently supported
non-rotation primitives (`x`, `h`, `z`, and `cx`), while `RotationStatement`
retains a `RotationAxis`, `QubitReference`, and `AngleLiteral`.

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
`schema_version` as $2$. Version $2$ separates declarations from statements and
serializes snapshot and optional durable node identities separately. AST fixtures
and frontend documents therefore evolve independently from execution traces and IR.

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
