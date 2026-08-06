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
- `rx(target, angle)`
- `ry(target, angle)`
- `rz(target, angle)`
- `cx(control, target)`
- `measure(target, key=None)`

## Angles and rotations

Rotations require an explicit `Angle`, created with `deg()`, `rad()`, or
`turns()`:

```python
program.rx(0, deg(190))
program.ry(1, rad(2))
program.rz(2, turns(0.25))
```

An `Angle` preserves its `source_value` and `source_unit` while carrying a
canonical `radians` value. The builder retains a bare numeric rotation argument
long enough for Daidalon to produce a source-linked diagnostic; it never guesses
whether `program.rx(0, 2)` means degrees, radians, or turns. The diagnostic asks
the author to write `rad(2)` or `deg(2)` explicitly.

## Source identity and locations

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

## Invariants

1. Qubit indices are zero-based and must be within the declared program width.
2. A controlled operation may not use the same qubit as control and target.
3. Source-level operations preserve insertion order.
4. Measurement is explicit; simulation reports probabilities without sampling unless sampling is requested by a future API.
5. The compiler, not the source builder, owns semantic validation.
6. Snapshot operation IDs are deterministic within a program snapshot and preserve
   operation insertion order, but are not durable across source edits.
7. Persisted editor state must use frontend-supplied durable source node IDs rather
   than snapshot operation IDs.

## Basis direction

The next language revision will attach an explicit basis descriptor to preparation, observation, and debugging operations. Basis conversion must appear in IR rather than being inferred by a backend.
