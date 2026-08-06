# Roadmap

## Foundation — current

- Python-first program builder
- semantic circuit IR
- Daidalon validation and lowering
- reference state-vector simulation
- Theonoe state reports
- ASCII circuit visualization
- CLI and examples

## Next sequence

1. structured trace view models and CLI step navigation;
2. typed angles with `RX`, `RY`, and `RZ` rotation gates;
3. explanations for arbitrary rotations;
4. an interactive tutorial and Studio trace panel.

Typed angles will be implemented with the first rotation gates rather than as an
isolated numeric feature. The language will accept explicit `deg()`, `rad()`, and
possibly `turns()` values; compiler and IR will preserve source-unit display
metadata while normalizing canonical radians for simulation. Bare numeric rotation
arguments should produce a diagnostic instead of guessing a unit.

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
