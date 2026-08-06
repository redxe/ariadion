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

## Object model

Objects clarify ownership, invariants, and relationships; they do not justify
elaborate inheritance trees. See [Object model, ownership, and identity
boundaries](object-model.md) for aggregate ownership, immutable value objects,
stable cross-layer identity, composition guidance, future substitution ports, and
native-language modeling rules.

## Packages

### `ariadion-language`

A small Python-first builder. It records user intent and source-level operations,
including explicit degree, radian, and turn-based rotation angles. It deliberately
does not simulate or optimize.

### `ariadion-core`

Shared identity, source-reference, source-range, and deterministic serialization
contracts. It has no dependency on language syntax, IR, compilers, or backends.

### `ariadion-ir`

Stable dataclasses for qubits, operations, circuits, IR provenance, and canonical
rotation radians with optional source-display metadata. Provider adapters should
target this layer rather than source objects.

### `daidalon`

Validates source programs and lowers them to semantic IR. Future compiler passes will include canonicalization, decomposition, routing, resource estimation, and backend-specific lowering.

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
