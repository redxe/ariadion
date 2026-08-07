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
- declaration-order `dense-no-reuse-v1` logical-slot allocation artifacts and logical-to-IR provenance
- `ObservationResultValue` declarations, structured return shapes, readout plans, and exact terminal joint classical distributions
- terminal analytical observation projection with no sampling, collapse, or mid-circuit feedback
- typed `SemanticAngle` and `LogicalRotationOperation` lowering to existing `RX`, `RY`, and `RZ` IR
- safe valid-Python `@quantum` AST capture into `LogicalProgram`
- source-provider boundary with inspected and explicit in-memory source
- source-derived identities, source ranges, inferred typed returns, and unresolved quantum parameters

## Next sequence

The next implementation work must preserve this order:

1. Add function composition, explicit quantum-input binding, and lifetime/escape analysis beyond `dense-no-reuse-v1`.
2. Define sampled terminal and mid-circuit execution: shots, seeds, outcomes, collapse, feedback, reset, and post-measurement traces.
3. Define noise-channel contracts and bind them to simulation requests.
4. Add a small density-matrix noisy simulator.
5. Add scheduling and T1/T2 idle decoherence.
6. Add reliability goals and bare-execution estimates.
7. Add pluggable protection-planning interfaces.
8. Add encoded-QEC simulation and decoder integration later.

## Milestone 1 — value, effect, and observation contracts

- public `Qubit` and `Bit` domain contracts
- internal logical-value identities and pre-allocation operations
- explicit and inferred observation contracts with typed bases, reasons, and result IDs
- tagged structured returns containing classical results and quantum values
- exact terminal joint-return distributions that preserve correlation without claiming sampled collapse
- classical, quantum, and hybrid function-effect contracts
- source-level aliasing, escape, reset, and conversion rules
- diagnostics with original Python-compatible source ranges

## Milestone 2 — hand-built logical allocation slice

- hand-build a logical Bell program using semantic identities
- lower it through Daidalon into allocated `CircuitIR`
- add `LogicalSlotAllocationPlan`, `ReadoutPlan`, observation metadata, typed rotation lowering, and logical-to-IR provenance
- run the resulting IR through simulation, trace capture, inspection, joint classical calculation, and quantum return handles
- use deterministic declaration-order allocation with no reuse or lifetime analysis

## Milestone 3 — decorated Python frontend and inferred observations — complete

- `@quantum` captures a safe valid-Python subset using Python's AST without calling the function body
- local `Qubit()` declarations, aliases, typed quantum parameters, and exact marker-identity resolution for `h`, `x`, `z`, `cx`, `rx`, `ry`, and `rz`
- `deg`, `rad`, and `turns` rotation literals preserve typed semantic source units
- Python annotations and return expressions become tagged `ReturnShape` values; terminal `Qubit`-to-`Bit` observations are inferred only for classical leaves
- quantum return leaves remain unobserved retained-state handles
- explicit source-provider contracts preserve absolute ranges and deterministic IDs for inspected files and in-memory buffers
- unsupported constructs receive source-linked frontend diagnostics; `.ari` loading and native parsing remain deferred
- next frontend work is composition, explicit binding, ownership/lifetime analysis, and then justified extension syntax

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
