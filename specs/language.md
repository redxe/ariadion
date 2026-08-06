# Ariadion language model — draft 0

The initial API is embedded in Python. A source program declares a fixed number of qubits and appends explicit operations.

```python
program = Program(2, name="bell")
program.h(0)
program.cx(0, 1)
```

## Current operations

- `x(target)`
- `h(target)`
- `z(target)`
- `cx(control, target)`
- `measure(target, key=None)`

## Source identity and locations

Each `Program` owns a deterministic source-ID namespace. By default it is
`program:<name>`; a frontend should pass a stable value such as a project-relative
file path through `Program(..., source_id="examples/bell.py")` when it needs IDs
that remain distinct across source units.

Every operation appended through the builder receives an ID of the form
`<program-source-id>:operation:<insertion-index>`. IDs are never derived from a
memory address or random value, and lowering preserves them unchanged.

The builder captures the caller's file and one-based line number when Python makes
that information available. A frontend with richer location data can pass an
explicit `SourceRange` to any operation method, including one-based `column`,
`end_line`, and `end_column` values. Locations are optional; the operation ID is
always present for builder-created operations.

Compiler diagnostics retain their diagnostic code and operation index, then expose
the same `source_id` and `source_range` through their immutable source reference.
Program-wide diagnostics may have no source reference; their messages remain useful
without a file or position.

## Invariants

1. Qubit indices are zero-based and must be within the declared program width.
2. A controlled operation may not use the same qubit as control and target.
3. Source-level operations preserve insertion order.
4. Measurement is explicit; simulation reports probabilities without sampling unless sampling is requested by a future API.
5. The compiler, not the source builder, owns semantic validation.
6. Source-operation IDs are deterministic within a program source namespace and
	preserve operation insertion order.

## Basis direction

The next language revision will attach an explicit basis descriptor to preparation, observation, and debugging operations. Basis conversion must appear in IR rather than being inferred by a backend.
