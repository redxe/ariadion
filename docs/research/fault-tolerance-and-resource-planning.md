# Fault tolerance and resource-planning design evidence

**Documentation consulted:** 2026-08-06.

This record explains why Ariadion treats reliability and protection as a planning
layer between scheduled logical operations and allocated `CircuitIR`. It does not
implement a threshold calculator, decoder, code-distance selector, encoded-QEC
layout, or physical-resource allocator.

## Engineering claim: there is no universal QEC threshold constant

Ashley M. Stephens studies surface-code fault-tolerance thresholds under multiple
noise models, measurement circuits, and decoders. The reported threshold range is
0.502(1)% to 1.140(1)% per gate, and the paper attributes the variation to those
assumptions.

**Ariadion decision:** no API or planner embeds one global threshold. A future
protection decision must depend on the algorithm schedule, noise profile, backend
architecture, QEC code, decoder, required error budget, operation count, idle time,
measurement count, correlations, and leakage.

**Limitations:** published thresholds do not directly provide resource estimates for
a different processor, error model, syndrome circuit, or decoder. A future planner
must retain the assumptions behind every estimate.

## Engineering claim: below-threshold error suppression is empirical and conditional

Google Quantum AI and Collaborators report that increasing surface-code size
suppresses logical error only when physical errors are below a critical threshold.
The publication has a 2026 author correction, so both the original and correction
must be cited when Ariadion refers to this result. The open preprint abstract
reports a distance-7 memory using 101 qubits and $0.143\% \pm 0.003\%$ error per
error-correction cycle; Ariadion treats that number as a platform-specific empirical
example, not a universal physical-qubit or code-distance formula.

**Ariadion decision:** a `ProtectionPlan` records a selected strategy, optional code
name/distance, estimated failure probability, physical-qubit count, and explicit
assumptions. A source `Qubit` remains representation-agnostic. Future planner terms
such as `ProtectedRealization`, `EncodedQubitPlan`, or `FaultTolerantRealization`
avoid overloading `LogicalQubit`, which already describes a source-semantic value.

**Limitations:** this evidence does not establish that Ariadion can reproduce the
demonstration, select a surface code, or estimate a protected realization. Those
need calibration, scheduling, decoding, and encoded-QEC simulation work.

## Engineering claim: leakage needs a separate model

K. C. Miao and collaborators describe leakage as leaving the computational state
space, accumulating and spreading through multi-qubit interactions, creating
correlated errors, and degrading expected logical-error suppression.

**Ariadion decision:** `LeakageModel` is distinct from ordinary gate-channel and
readout-noise contracts. A `CorrelationModel` remains separate as well, because an
independent error probability cannot describe every correlated event.

**Limitations:** the current fields only record assumptions; they do not define
leakage-reduction circuits, return dynamics, leakage-aware decoding, or correlated
channel evolution.

## Engineering claim: planning should consume intent and models

Microsoft's Quantum Resource Estimator documentation separates an application
model, hardware/architecture model, error-correction or factory model, and maximum
error budget. It explores resource choices and reports a Pareto-optimal
physical-qubit/runtime frontier that fits the error budget.

**Ariadion decision:** source code may state success intent such as
`reliability=0.999999` and `protection="auto"`; the compiler translates that to a
failure budget. The programmer does not choose physical-qubit count or code distance
unless explicitly using an advanced policy override.

**Limitations:** Microsoft’s estimator is a precedent for the planning shape, not
an Ariadion implementation dependency, backend, or resource model.

## Required future decision process

1. Compile and schedule the logical algorithm.
2. Estimate unprotected failure under the chosen noise profile.
3. Compare it with the reliability goal.
4. Use a bare realization when it satisfies the goal.
5. Otherwise evaluate compatible protection candidates.
6. Reject candidates whose assumptions place them above threshold.
7. Estimate code distance, physical qubits, runtime, and total failure.
8. Return Pareto-optimal feasible plans.
9. Report when no supported plan meets the goal.

This process deliberately separates semantic intent from eventual physical
allocation. It may report unsupported models or no feasible plan rather than invent
an allocation or silently weaken a reliability goal.

## References

1. A. M. Stephens, [“Fault-tolerant thresholds for quantum error correction with the surface code”](https://arxiv.org/abs/1311.5003), *Physical Review A* 89, 022321 (2014), arXiv:1311.5003, consulted 2026-08-06.
2. Google Quantum AI and Collaborators, [“Quantum error correction below the surface code threshold”](https://doi.org/10.1038/s41586-024-08449-y), *Nature* 638, 920–926 (2025), DOI: 10.1038/s41586-024-08449-y, consulted 2026-08-06.
3. [“Author Correction: Quantum error correction below the surface code threshold”](https://doi.org/10.1038/s41586-026-10559-8), *Nature* 653, E5 (2026), DOI: 10.1038/s41586-026-10559-8, consulted 2026-08-06.
4. Google Quantum AI and Collaborators, [open preprint record for the QEC result](https://arxiv.org/abs/2408.13687), arXiv:2408.13687, consulted 2026-08-06.
5. K. C. Miao et al., [“Overcoming leakage in quantum error correction”](https://doi.org/10.1038/s41567-023-02226-w), *Nature Physics* 19, 1780–1786 (2023), DOI: 10.1038/s41567-023-02226-w, consulted 2026-08-06.
6. [Microsoft Quantum Resource Estimator documentation](https://learn.microsoft.com/en-us/azure/quantum/intro-to-resource-estimation), official technical documentation, consulted 2026-08-06.
