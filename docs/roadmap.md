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
- hand-built `LogicalProgram` allocation through `CircuitIR`, trace, and inspection
- declaration-order `dense-no-reuse-v1` allocation artifacts and logical-to-IR provenance

## Next sequence

The next implementation work must preserve this order:

1. Prototype `@quantum` capture with Python AST.
2. Infer terminal observations at `Qubit`-to-`Bit` boundaries.
3. Add lifetime analysis and slot reuse beyond `dense-no-reuse-v1`.
4. Define noise-channel contracts and bind them to simulation requests.
5. Add a small density-matrix noisy simulator.
6. Add scheduling and T1/T2 idle decoherence.
7. Add reliability goals and bare-execution estimates.
8. Add pluggable protection-planning interfaces.
9. Add encoded-QEC simulation and decoder integration later.

## Milestone 1 — value, effect, and observation contracts

- public `Qubit` and `Bit` domain contracts
- internal logical-value identities and pre-allocation operations
- explicit and inferred observation contracts with typed bases and reasons
- classical, quantum, and hybrid function-effect contracts
- source-level aliasing, escape, reset, and conversion rules
- diagnostics with original Python-compatible source ranges

## Milestone 2 — hand-built logical allocation slice

- hand-build a logical Bell program using semantic identities
- lower it through Daidalon into allocated `CircuitIR`
- add `AllocationPlan` and logical-to-IR provenance
- run the resulting IR through simulation, trace capture, and inspection
- use deterministic declaration-order allocation with no reuse or lifetime analysis

## Milestone 3 — decorated Python frontend and inferred observations

- `@quantum` capture using Python's AST
- logical `Qubit()` creation and typed quantum parameters
- infer terminal `Qubit`-to-`Bit` observations
- add extension-aware diagnostics and source transformation only when justified
- defer `.ari` loading and editor parsing until the valid-Python path is proven

## Milestone 4 — staged noisy simulation and reliability planning

- define channel, leakage, correlation, and device-profile contracts
- add a small density-matrix noisy simulator
- schedule operations and model T1/T2 idle decoherence
- estimate bare-execution failure against reliability goals
- add pluggable protection-planning interfaces and Pareto resource reporting
- add encoded-QEC simulation and decoder integration only after these earlier slices

## Milestone 5 — interactive debugging

- operation-by-operation snapshots
- breakpoints and watch expressions
- reduced density matrices
- phase and interference explanations
- entanglement provenance

## Milestone 6 — Studio

- editor and language server
- synchronized code/circuit/state panes
- resource estimates
- project-driven tutorials
- reproducible Capsules

## Milestone 7 — providers and distribution

- provider-neutral execution protocol
- cloud hardware adapters
- distributed simulator workers
- coordinator and friend-compute trust model
