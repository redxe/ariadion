# Noise-modeling design evidence

**Documentation consulted:** 2026-08-06.

This record grounds Ariadion's future noise-modeling and mixed-state simulation
interfaces. It defines architectural evidence only; Ariadion does not yet ingest
backend calibrations, simulate noise channels, evolve density matrices, or execute
stochastic trajectories.

## Engineering claim: separate device profiles from individual channels

Qiskit Aer documents `NoiseModel.from_backend()` as an approximate device-derived
model assembled from backend properties. Its documented approximation combines
single- and two-qubit gate errors, thermal relaxation, and single-qubit readout
errors. That is evidence that a backend or device profile is a collection of
separate assumptions, not one universal error scalar.

**Ariadion decision:** `NoiseProfile` groups `GateNoise`, `IdleNoise`,
`ReadoutNoise`, `LeakageModel`, and `CorrelationModel` without giving a source
`Qubit` a physical address. A `GateNoise` names a gate/channel assumption; the
profile owns their composition and later backend-specific interpretation.

**Limitations:** this contract does not prescribe a channel representation,
calibration schema, target selector, composition order, or a conversion from any
specific provider's backend object. Those require a future backend-ingestion and
simulation vertical slice.

## Engineering claim: decoherence depends on time and scheduling

Qiskit Aer documents `thermal_relaxation_error` with $T_1$, $T_2$, and operation
or delay duration inputs. It also records the physical validity condition
$T_2 \leq 2T_1$.

**Ariadion decision:** `IdleNoise` records validated optional $T_1$ and $T_2$ time
constants, including the condition when both are supplied. A future compiler must
produce a logical operation schedule before it can estimate gate-time or idle-time
decoherence. Reliability analysis therefore belongs after scheduling and before
protection/allocation planning.

**Limitations:** a pair of time constants is not a complete device model. It does
not capture temperature, frequency, non-Markovian behavior, pulse shape, drift, or
multi-qubit correlations. The current contract does not calculate thermal
relaxation probabilities.

## Engineering claim: mixed-state channels need a distinct numerical path

Google Quantum AI's Cirq documentation describes `DensityMatrixSimulator` as a
simulator for density matrices and noisy circuits. Its `cirq.kraus` documentation
describes channel operations through Kraus operators, including the standard
trace-preserving condition $\sum_k A_k^\dagger A_k = I$ and state evolution
$\rho \mapsto \sum_k A_k \rho A_k^\dagger$.

**Ariadion decision:** channel assumptions are modeled separately from the ideal
state-vector reference simulator. A composable `SimulationRequest` separates the
numerical `EvolutionModel`, `NoiseModelOrigin`, selected `NoiseFeature` values, and
an optional `ProtectionPlan`. A future exact small noisy-circuit path can use
density matrices; larger models may need trajectories, stabilizer-specialized
methods, or dedicated encoded-QEC simulation instead.

**Limitations:** the contracts do not imply that every noise profile has a Kraus
form that is practical to evaluate, that density matrices scale to large circuits,
or that one simulator engine can cover every requested dimension combination.

## Contract implications

- `GateNoise` keeps a named operation/channel assumption and an optional gate
  duration separate from the source-level value model.
- `IdleNoise` holds physical time constants, while a future schedule supplies the
  actual idle durations.
- `ReadoutNoise` is independent from gate errors because observation is its own
  semantic boundary.
- `LeakageModel` and `CorrelationModel` are explicit optional components rather
  than silently folded into independent computational-basis channels.
- `SimulationRequest` records independent modeling dimensions; it is not evidence
  that the requested engine or protected realization is available.

## References

1. [Qiskit Aer `NoiseModel` documentation](https://qiskit.github.io/qiskit-aer/stubs/qiskit_aer.noise.NoiseModel.html), official technical documentation, consulted 2026-08-06.
2. [Qiskit Aer `thermal_relaxation_error` documentation](https://qiskit.github.io/qiskit-aer/stubs/qiskit_aer.noise.thermal_relaxation_error.html), official technical documentation, consulted 2026-08-06.
3. [Google Quantum AI Cirq `DensityMatrixSimulator` documentation](https://quantumai.google/reference/python/cirq/DensityMatrixSimulator), official technical documentation, consulted 2026-08-06.
4. [Google Quantum AI Cirq `cirq.kraus` documentation](https://quantumai.google/reference/python/cirq/kraus), official technical documentation, consulted 2026-08-06.
