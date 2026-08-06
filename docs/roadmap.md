# Roadmap

## Foundation — current

- Python-first program builder
- semantic circuit IR
- Daidalon validation and lowering
- reference state-vector simulation
- Theonoe state reports
- ASCII circuit visualization
- CLI and examples
- structured trace view models and CLI step navigation
- typed angles with `RX`, `RY`, and `RZ` rotation gates
- human-readable, structured explanations for arbitrary rotations
- immutable syntax identities, source literals, and schema-versioned frontend contracts

## Next sequence

1. define the Python-extension language contract;
2. add logical quantum-value and ownership contracts;
3. infer resource width, lifetimes, and allocation plans in Daidalon;
4. prototype `@quantum` with valid Python syntax;
5. connect decorated functions to the existing IR, runtime, and debugger;
6. add justified extension syntax such as angle suffixes and basis-aware measurement;
7. add editor parsing, `.ari` loading, tutorials, and Studio support.

## Milestone 1 — managed language semantics

- logical quantum-value identities and handles
- public `Qubit` and `Bit` domain contracts
- ownership, aliasing, measurement, reset, and escape rules
- inferred classical, quantum, and hybrid function effects
- lifetime analysis, allocation plans, and resource reports
- explicit computational and custom bases
- measurement values, classical control, and reusable quantum functions
- diagnostics with original Python-compatible source ranges

## Milestone 2 — decorated Python frontend

- `@quantum` capture using Python's AST
- logical `Qubit()` creation and typed quantum parameters
- lowering through Daidalon into allocated `CircuitIR`
- source-to-trace links that display logical names
- extension-aware diagnostics and source transformation

## Milestone 3 — interactive debugging

- operation-by-operation snapshots
- breakpoints and watch expressions
- reduced density matrices
- phase and interference explanations
- entanglement provenance

## Milestone 4 — Studio

- editor and language server
- synchronized code/circuit/state panes
- resource estimates
- project-driven tutorials
- reproducible Capsules

## Milestone 5 — providers and distribution

- provider-neutral execution protocol
- cloud hardware adapters
- distributed simulator workers
- coordinator and friend-compute trust model
