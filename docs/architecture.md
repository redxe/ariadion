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

## Packages

### `ariadion-language`

A small Python-first builder. It records user intent and source-level operations. It deliberately does not simulate or optimize.

### `ariadion-core`

Shared identity, source-reference, source-range, and deterministic serialization
contracts. It has no dependency on language syntax, IR, compilers, or backends.

### `ariadion-ir`

Stable dataclasses for qubits, operations, circuits, and IR provenance. Provider
adapters should target this layer rather than source objects.

### `daidalon`

Validates source programs and lowers them to semantic IR. Future compiler passes will include canonicalization, decomposition, routing, resource estimation, and backend-specific lowering.

### `ariadion-simulator`

A dependency-free state-vector reference backend. It favors clarity and correctness over performance.

### `theonoe`

Builds inspectable snapshots: basis probabilities, amplitudes, phase, and lightweight entanglement signals. Future work includes time travel, breakpoints, reduced density matrices, and causal explanations.

### `ariadion-visualization`

Turns semantic IR and execution snapshots into textual or structured views. The IDE should consume structured view models rather than scrape rendered strings.

### `ariadion-runtime`

Coordinates compilation, execution, inspection, and rendering. It is the first vertical slice used by the CLI, examples, and future Studio.

## Near-term vertical slice

```text
write -> validate -> lower -> render -> simulate -> inspect
```

A change is considered vertically complete only when it can be exercised from the SDK and covered by a runtime-level test.
