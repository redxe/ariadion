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
- native Ariadion grammar and immutable source AST contracts

## Next sequence

1. define named quantum registers and explicit basis semantics;
2. lex and parse `.ari` files into the source AST;
3. add name resolution and a typed semantic model;
4. lower native programs through Daidalon into existing IR;
5. run `.ari` files through the current CLI and debugger;
6. add an interactive tutorial and Studio trace panel.

## Milestone 1 — language semantics

- named quantum registers
- explicit computational and custom bases
- measurement values and classical control
- reusable quantum functions
- diagnostics with source ranges

## Milestone 2 — interactive debugging

- operation-by-operation snapshots
- breakpoints and watch expressions
- reduced density matrices
- phase and interference explanations
- entanglement provenance

## Milestone 3 — Studio

- editor and language server
- synchronized code/circuit/state panes
- resource estimates
- project-driven tutorials
- reproducible Capsules

## Milestone 4 — providers and distribution

- provider-neutral execution protocol
- cloud hardware adapters
- distributed simulator workers
- coordinator and friend-compute trust model
