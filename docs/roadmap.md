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
- `LogicalModule` call graphs with explicit quantum argument bindings and acyclic validation
- materialized invocation-aware call expansion with definition and invocation provenance
- expanded logical lifetime analysis and conservative `expanded-dense-no-reuse-v1` allocation
- callee-local `Qubit()` instantiation and scalar `Qubit` call-result aliases

## Next sequence

The next implementation work must preserve this order:

1. Define sampled terminal and mid-circuit execution: shots, seeds, outcomes, collapse, feedback, reset, and post-measurement traces.
2. Define noise-channel contracts and bind them to simulation requests.
3. Add a small density-matrix noisy simulator.
4. Add scheduling and T1/T2 idle decoherence.
5. Add reliability goals and bare-execution estimates.
6. Add pluggable protection-planning interfaces.
7. Add encoded-QEC simulation and decoder integration later.

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
- future frontend extensions require explicit ownership and allocation-policy contracts

## Milestone 4 — composed quantum functions and logical bindings — complete

- preserve a quantum-function call as `LogicalCallOperation` rather than textual substitution
- resolve a deterministic, acyclic `LogicalModule` from a root `QuantumFunction`
- bind callee `QuantumParameter` identities to caller logical values explicitly
- materialize module calls in Daidalon before allocation through an immutable `ExpandedLogicalProgram`
- instantiate every callee-local definition once per deterministic call instance while preserving parameter aliases
- support one-target scalar `Qubit` call results as aliases, never copied quantum states
- analyze expanded quantum-value lifetimes and preserve call/return escape evidence
- allocate all expanded values with `expanded-dense-no-reuse-v1`; lifetime analysis exists but slot reuse remains deferred
- retain callee definition source plus structured invocation `CallFrameProvenance`
- generate invocation-specific deterministic IR operation IDs
- reject closures, recursion, stale source-only capture assumptions, classical and tuple call results, callee observations, and unbound module-entry inputs

## Milestone 5 — staged noisy simulation and reliability planning

- define channel, leakage, correlation, and device-profile contracts
- add a small density-matrix noisy simulator
- schedule operations and model T1/T2 idle decoherence
- estimate bare-execution failure against reliability goals
- add pluggable protection-planning interfaces and Pareto resource reporting
- add encoded-QEC simulation and decoder integration only after these earlier slices

## Milestone 6 — interactive debugging

- operation-by-operation snapshots
- breakpoints and watch expressions
- reduced density matrices
- phase and interference explanations
- entanglement provenance

## Milestone 7 — Studio

- editor and language server
- synchronized code/circuit/state panes
- resource estimates
- project-driven tutorials
- reproducible Capsules

## Milestone 8 — providers and distribution

- provider-neutral execution protocol
- cloud hardware adapters
- distributed simulator workers
- coordinator and friend-compute trust model
