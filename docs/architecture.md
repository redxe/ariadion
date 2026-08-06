# Architecture

## Product boundary

Ariadion is both a programming model and an interactive environment. The initial architecture keeps the semantic core independent of any particular IDE, simulator, or cloud provider.

## Dependency direction

```text
ariadion-core
    ├── ariadion-language ─┐
    └── ariadion-ir ───────┼── Daidalon ──> ariadion-runtime
                                                    │                    ├── simulator
Ariadion SDK ─────────────┴────────────────────┼── Theonoe
                                                                                             └── visualization
```

The compiler produces immutable semantic IR. Runtime backends consume IR. Debuggers and visualizations observe execution artifacts but do not change source semantics. `ariadion-core` owns neutral identity and source-location contracts so the language model and IR remain siblings. Daidalon preserves source references in lowered operations and diagnostics while assigning distinct IR-operation IDs for generated compiler output.

`ariadion-syntax` currently depends only on `ariadion-core`. A future resolved and
typed source-semantic model will bridge Python-compatible extension syntax into
Daidalon without making the syntax package depend on IR, runtime, simulators, or
Theonoe.

## Frontend and managed allocation

The public language direction is a managed Python quantum extension. Programmers
create and manipulate logical quantum values; allocation, reuse, layout, and
physical-resource mapping are compiler responsibilities. The intended frontend is:

```text
Python-compatible Ariadion source
    ↓
extension-aware tokenization / source transformation
    ↓
Python AST + Ariadion extension nodes
    ↓
resolved quantum semantic model
    ↓
lifetime and resource analysis
    ↓
allocated provider-neutral CircuitIR
    ↓
simulator or hardware backend
```

The Python parser retains ownership of ordinary Python. Ariadion recognizes only
explicit quantum constructs, preserving exact original source ranges and identities
through transformation. A standalone parser for `program name` and `qubits data[2]`
is not on the current path.

The allocated `CircuitIR` continues to use dense integer targets and an explicit
`qubit_count`; those are compiler results. Daidalon will expose a logical-to-IR
allocation artifact for diagnostics, resource reporting, trace navigation, and
later hardware mapping.

At the public boundary, `Qubit` is already a logical value and `Bit` is a distinct
classical observation result. `LogicalQubitId`, `LogicalQubitValue`, and
`LogicalOperationId` are compiler-semantic identities; allocated slots and integer
targets are backend-facing facts. No public `Qubit` constructor accepts a physical
or simulator location.

## Object model

Objects clarify ownership, invariants, and relationships; they do not justify
elaborate inheritance trees. See [Object model, ownership, and identity
boundaries](object-model.md) for aggregate ownership, immutable value objects,
stable cross-layer identity, composition guidance, future substitution ports, and
native-language modeling rules.

## Packages

### `ariadion-language`

A small width-based Python builder for the current vertical slice. It records
already allocated integer-target operations, including explicit degree, radian,
and turn-based rotation angles. Alongside the builder, the package exposes
immutable public `Qubit` and `Bit` domain values without adding them to the
width-based API. The builder is a compatibility and migration mechanism; its next
prototype will operate on `Qubit` values instead of requiring `Program(width)`.

### `ariadion-semantics`

Immutable pre-allocation contracts for logical quantum values, logical operations,
bases, observations, and function effects. It depends only on `ariadion-core` and
contains no allocated integer targets, circuit width, backend policy, or lowering.
Daidalon will consume these contracts for lifetime analysis and allocation.

### `ariadion-syntax`

Immutable token and source-contracts for extensions embedded in Python-compatible
source. It preserves exact spelling, basis expressions, angle suffixes, complete
source ranges, and snapshot syntax-node IDs with optional durable editor IDs. Its
schema-v3 named-register document model remains compatibility data, not the future
public grammar. It does not parse all of Python, resolve names, allocate resources,
calculate canonical values, or depend on compiled IR. See [the syntax
specification](../specs/syntax.md).

### `ariadion-core`

Shared identity, source-reference, source-range, and deterministic serialization
contracts. It has no dependency on language syntax, IR, compilers, or backends.

### `ariadion-ir`

Stable dataclasses for qubits, operations, circuits, IR provenance, and canonical
rotation radians with optional source-display metadata. Provider adapters should
target this layer rather than source objects. Its integer targets and
`CircuitIR.qubit_count` represent an allocated circuit, not user-written resource
allocation.

### `daidalon`

Validates resolved quantum programs, performs lifetime and resource analysis,
creates allocation plans, and lowers them to semantic IR. Future compiler passes
will include canonicalization, decomposition, routing, resource estimation, and
backend-specific lowering.

### `ariadion-simulator`

A dependency-free state-vector reference backend. It favors clarity and correctness
over performance, including standard `RX`, `RY`, and `RZ` matrices over canonical
radians. When explicitly enabled, it retains raw immutable amplitude transitions,
but it does not depend on runtime trace contracts or interpret those states.

### `theonoe`

Builds inspectable snapshots: basis probabilities, amplitudes, phase, reduced
density matrices, purity-based separability facts, and explicitly heuristic
subsystem groups. Runtime exposes an explicit projection from immutable execution
traces to these analyses; Theonoe neither mutates traces nor controls simulation.
For rotation steps, it accepts primitive operation facts alongside an inspected
transition to produce structured exact effects and a separately labeled
educational interpretation. It does not import runtime trace contracts.

### `ariadion-visualization`

Turns semantic IR and execution snapshots into textual or structured views. The IDE should consume structured view models rather than scrape rendered strings.

### `ariadion-runtime`

Coordinates compilation, execution, inspection, and rendering. It is the first vertical slice used by the CLI, examples, and future Studio.

It also owns the versioned execution-trace contract consumed by debugger and Studio
clients. It adapts simulator raw capture into that contract and projects it through
Theonoe only when a consumer explicitly requests inspection, so capture and
interpretation remain independently selectable. Its frontend-neutral
`TraceDebuggerSession` and `TraceStepViewModel` compose IR, trace, and inspection
data without managing terminal interaction.

### `ariadion-cli`

Loads a Python file's top-level program builder and provides trace rendering plus
interactive step navigation. Its terminal renderer consumes runtime view models;
Studio can reuse those models without scraping CLI text.

## Near-term vertical slice

```text
write -> validate -> lower -> render -> simulate -> inspect
```

A change is considered vertically complete only when it can be exercised from the SDK and covered by a runtime-level test.
