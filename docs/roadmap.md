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
- exact terminal analytical observation projection plus explicit sampled collapse and mid-circuit gates
- typed `SemanticAngle` and `LogicalRotationOperation` lowering to existing `RX`, `RY`, and `RZ` IR
- safe valid-Python `@quantum` AST capture into `LogicalProgram`
- source-provider boundary with inspected and explicit in-memory source
- source-derived identities, source ranges, explicit/inferred typed returns, and unresolved quantum parameters
- `LogicalModule` call graphs with explicit quantum argument bindings and acyclic validation
- materialized invocation-aware call expansion with definition and invocation provenance
- expanded logical lifetime analysis and conservative `expanded-dense-no-reuse-v1` allocation
- callee-local `Qubit()` instantiation and scalar `Qubit` call-result aliases
- explicit quantum ownership and release-safety evidence separate from liveness
- seeded sampled state-vector trajectories with collapse, empirical counts, and one-shot traces
- sampled source/IR reset through collapse plus conditional `X`; exact reset rejection with `A203`
- exact density-matrix execution with typed one-qubit Kraus channels, exact reset,
  and physical versus readout-reported distributions
- explicit simulation backend capabilities, inspectable selection plans, and
	optional NumPy `complex128` local kernels while preserving reference semantics
- operation scheduling with executable T1/T2 idle decoherence
- immutable noise-impact explanations and bare-execution reliability estimates

## Current sequence status

The reliability sequence has completed its first three slices:

1. Add scheduling and T1/T2 idle decoherence. (complete)
2. Add noise-impact explanations. (complete)
3. Add bare reliability estimation. (complete)
4. Add pluggable protection-planning interfaces, then encoded-QEC simulation and
	decoder integration later. (deferred; keep separate from release foundations)

After the noise-channel and density-matrix work has established a clean execution
model, return to classical feedback, branching, and conditional gates.

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

## Milestone 3 — decorated Python frontend and observations — complete

- `@quantum` captures a safe valid-Python subset using Python's AST without calling the function body
- local `Qubit()` declarations, aliases, typed quantum parameters, and exact marker-identity resolution for `h`, `x`, `z`, `cx`, `rx`, `ry`, `rz`, `observe`, and `reset`
- `deg`, `rad`, and `turns` rotation literals preserve typed semantic source units
- Python annotations and return expressions become tagged `ReturnShape` values; ordinary `Qubit`-to-`Bit` returns infer terminal observations while explicit `observe()` captures a named observation result
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
- distinguish entry-parameter ownership from local ownership and emit release-safety evidence
- keep semantic lifetime peaks separate from allocated execution width; `discard_required` never permits reuse
- retain callee definition source plus structured invocation `CallFrameProvenance`
- generate invocation-specific deterministic IR operation IDs
- reject closures, recursion, stale source-only capture assumptions, classical and tuple call results, callee observations, and unbound module-entry inputs

## Milestone 4.5 — sampled collapse and release safety — complete

- preserve exact terminal measurement analysis and reject exact mid-circuit operations after observation (`A202`)
- expose explicit `SampledExecutionRequest(shots, seed)` rather than inferring execution mode
- independently initialize each sampled trajectory, collapse sampled measurements, and permit later gates
- expose sampled outcomes, empirical joint counts, and sampled result classes separately from exact distributions
- establish sampled-only IR `RESET` execution and reject exact reset (`A203`)
- retain one sampled trajectory in a trace and reject multi-shot trace capture (`A204`)
- classify local values as `discard_required` without implementing or authorizing slot reuse

## Milestone 4.6 — explicit source observation and reset — complete

- expose non-executing `observe` and `reset` AST markers through the public SDK
- bind `result = observe(q)` to one `ObservationResultValue` with
	`ObservationReason.EXPLICIT`; returning or aliasing that `Bit` never inserts a
	second observation
- preserve discarded explicit observations in semantic/readout/trace artifacts
- lower `LogicalResetOperation` to `RESET` while retaining the same logical value
	identity and provenance
- allow reset within composed `None`-returning helpers while keeping callee
	observations and classical call results unsupported
- enforce `A202` and `A203` only at exact execution; sampled behavior still
	requires explicit `SampledExecutionRequest`
- defer `Bit` branching, feedback, arithmetic, conditional gates, slot reuse, and
	scheduling and idle decoherence

## Milestone 4.7 — executable noise channel contracts — complete

- keep descriptive `NoiseProfile` metadata separate from typed,
	provider-neutral `ExecutableNoiseModel` channel data
- define one-qubit bit-flip, phase-flip, depolarizing, amplitude-damping, and
	phase-damping Kraus-channel contracts in neutral `ariadion-noise`
- bind channels to public `OneQubitGate` categories, never public allocated
	`OpCode` values, and reject `CX` until a multi-qubit channel representation exists
- model asymmetric classical readout with `BinaryReadoutChannel`, independent of
	density-matrix gate evolution
- preserve `IdleNoise(t1_ns, t2_ns)` as schedule-dependent descriptive input
- require `SimulationRequest` provenance to distinguish ideal, declared typed
	noise, and future device-profile references
- record assumptions and unsupported `NoiseFeature` values in `NoiseBindingResult`
- defer timing/scheduling, calibration ingestion, leakage, correlations, QEC, and
	automatic reliability planning

## Milestone 4.8 — exact density-matrix noisy execution — complete

- expose `DensityMatrixExecutionRequest` and dedicated density result types through
	  simulator, runtime, and SDK APIs
- evolve exact $2^n\times2^n$ density matrices for ideal `X`, `H`, `Z`, `RX`,
	  `RY`, `RZ`, and `CX`
- validate every custom one-qubit Kraus channel before execution, then apply its
	  matched channel after the ideal single-qubit gate
- preserve terminal exact observations and derive `ExactClassicalDistribution`
	  values from density diagonals
- distinguish physical classical distributions from independently readout-noised
	  reported distributions, including repeated result aliases
- execute exact trace-and-reprepare reset on entangled targets while preserving the
	  existing state-vector `A203` reset behavior
- reject amplitude-only trace capture for density execution (`A205`) instead of
	  fabricating amplitude snapshots
- defer two-qubit noise, timing/T1/T2 execution, calibration ingestion, sampling,
	  feedback, leakage, correlations, QEC, and slot reuse

## Milestone 4.9 — backend capabilities and optional NumPy kernels — complete

- define array-free `StateRepresentation`, `SimulationQuery`,
	`SimulationCapabilities`, `SimulationBackend`, and `SimulationPlan` contracts
	in `ariadion-simulator`
- retain current engines as explicit `reference-state-vector`,
	`reference-sampled-trajectory`, and `reference-density-matrix` wrappers rather
	than changing runtime's default reference behavior
- record `PERMUTATION`, `DIAGONAL`, `LOCAL_DENSE`,
	`CONTROLLED_PERMUTATION`, and `KRAUS_CHANNEL` operator metadata as inspectable
	local-kernel evidence
- validate exact density results as positive semidefinite within an explicit
	tolerance, in addition to existing Hermiticity and trace-one invariants
- add the separately installable `ariadion-simulator-numpy` CPU implementation
	using `complex128`, local/tensor transformations, indexed permutations, and
	local Kraus/reset maps without global gate matrices or superoperators
- keep NumPy selection explicit; defer automatic selection, JIT/GPU frameworks,
	stabilizer/tensor-network/distributed implementations, gate fusion, mixed
	precision, scheduling, and T1/T2 execution
- add reference/NumPy parity coverage and manual non-CI kernel benchmarks

## Milestone 5 — scheduling and reliability planning — partial

- schedule operations and model T1/T2 idle decoherence — complete
- explain the modeled noise impact in execution artifacts — complete
- define leakage, correlation, and device-profile ingestion contracts
- estimate bare-execution reliability against explicit goals — complete
- add pluggable protection-planning interfaces and Pareto resource reporting
- add encoded-QEC simulation and decoder integration only after these earlier slices

## Milestone 6 — interactive debugging

- operation-by-operation snapshots
- breakpoints and watch expressions
- reduced density matrices
- phase and interference explanations
- entanglement provenance
- deferred research: persistent computation artifacts for streamed/lazy traces,
  checkpoints, and distributed durability are documented in
  [persistent-computation-artifacts.md](research/persistent-computation-artifacts.md),
  associated mainly with Milestones 6 and 8, not Release Foundations scope.

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
