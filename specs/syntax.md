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

`ProgramSyntax` is the immutable root. Its ordered `items` contain
`QubitDeclaration`, `GateStatement`, `RotationStatement`, and
`MeasurementStatement` nodes. `GateStatement` represents the currently supported
non-rotation primitives (`x`, `h`, `z`, and `cx`), while `RotationStatement`
retains a `RotationAxis`, `QubitReference`, and `AngleLiteral`.

Every AST node contains a `SyntaxLocation`, which combines:

- a complete one-based `SourceRange`; and
- a non-empty durable `SourceNodeId`.

Node IDs must be unique within a `ProgramSyntax`. This lets an editor preserve
selection, breakpoints, and tutorial state across later resolution and lowering
stages without relying on Python object identity.

`Identifier`, `IntegerLiteral`, and `AngleLiteral` are source values rather than
semantic values. An `AngleLiteral` preserves spelling such as `90deg` or
`0.5turns`, its numeric source value, and its unit suffix. It does not calculate
canonical radians; typed semantic analysis will make that conversion later.

## Tokens and diagnostics

`TokenKind` and `Token` define the lexical vocabulary and preserve original token
spelling plus a complete source range. They are contracts for a future lexer, not
a parser implementation.

`SyntaxDiagnostic` is independent from Daidalon diagnostics. A lexer or parser can
report an `S...` source error with a source range before name resolution, type
checking, or IR lowering exists. Semantic diagnostics will remain a later layer.

## Serialization

AST values, tokens, source locations, and syntax diagnostics provide deterministic
`to_dict()` and canonical `to_json()` output. `ProgramSyntax` documents its
`schema_version` as `1`, allowing AST fixtures and frontend documents to evolve
independently from execution traces and IR.

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
