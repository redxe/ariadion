# Adaptive physical-realization design evidence

**Documentation consulted:** 2026-08-06.

This record explains why the first logical Bell slice lowers a small gate-shaped
instruction form, while preserving room for richer physical realization later. It
does not add a pulse compiler, calibration ingestion, Hamiltonian IR, analog
execution, control optimization, or hardware adapter.

## Current scope: a gate slice, not a universal physical language

The current executable path is intentionally narrow:

```text
LogicalProgram
    -> declaration-order dense allocation
    -> CircuitIR
    -> reference state-vector simulation
    -> execution trace and inspection
```

It lowers `LogicalGateOperation` values for the current gate subset and Z-basis
`Observation` values. `LogicalGateOperation` is one member of `QuantumInstruction`;
it is not a claim that every future Ariadion algorithm must be expressed as a list
of discrete gates.

A later realization stage may choose among:

```text
discrete gate sequence
extended native gate
unitary fusion
digital-analog evolution
optimized control waveform
```

The selected representation must depend on the target, available calibration and
control interfaces, correctness evidence, and cost model. It must not change the
meaning or identity of a public `Qubit` or an already resolved logical instruction.

## Engineering claim: native controls can realize larger instruction units

Cho et al. study direct pulse-level compilation for arbitrary quantum logic gates
on superconducting qutrits. Chen et al. study unified control for arbitrary
two-qubit gates and report a platform-specific average gate fidelity of 99.38%.
These results support an architecture in which a future compiler may select a
native or fused realization rather than forcing every semantic instruction through
a fixed universal-gate decomposition.

**Ariadion decision:** keep a resolved instruction identity stable while allowing
one logical instruction to lower to one or more IR operations and, later, to a
native-gate or pulse artifact. This is why IR provenance records parent logical
operation IDs separately from source-operation identity.

**Limitations:** the papers do not provide a portable pulse language, a common
calibration schema, or a correctness proof for Ariadion lowering. The current Bell
slice still emits only allocated `CircuitIR` gates and measurements.

## Engineering claim: Hamiltonian and analog forms need an independent path

SimuQ provides Hamiltonian-level programming, an abstract analog instruction set,
and solver-based pulse scheduling for heterogeneous analog devices. Garcia de
Andoin, Mueller, and Camacho describe digital-analog computation using natural
interaction Hamiltonians plus single-qubit gates, including explicit constructions
for arbitrary two-body Hamiltonians from local transforms of an Ising interaction.

**Ariadion decision:** future `QuantumInstruction` variants may include an
`EvolutionBlock`, `UnitaryBlock`, `AnalogInteraction`, or a control-native form.
They will be separate semantic forms, not subclasses or encodings of the current
gate opcode. A future pass can lower one of those forms to a digital sequence, an
analog evolution, or a control waveform while preserving source and semantic
provenance.

**Limitations:** this does not implement a Hamiltonian expression language,
HamiltonianIR, digital-analog scheduling, pulse generation, or an analog simulator.

## Engineering claim: adaptive lowering needs evidence and device boundaries

The QASMTrans preprint describes end-to-end circuit-to-pulse compilation, direct
QICK integration, and calibration-aware adaptation. It is preliminary evidence
only: its arXiv record includes an administrative note about substantial text
overlap with another preprint. Li et al.'s QBlue preprint instead demonstrates the
value of a high-level second-quantized Hamiltonian representation and mechanized
correctness across digital and analog compilation paths.

**Ariadion decision:** a future adaptive-realization pass needs explicit target
capabilities, calibration provenance, cost objectives, and validation or
equivalence evidence. A preprint or platform result may motivate a design boundary,
but it does not establish a performance promise for Ariadion.

**Limitations:** Ariadion has no adaptive pass, calibration ingestion, pulse
schedule representation, proof infrastructure, or equivalence checker today.

## Required architectural conclusion

**The current gate operation is one semantic instruction form. It must not prevent
future Hamiltonian-, unitary-, analog-, or control-level representations.**

This conclusion keeps source semantics stable while allowing target-specific
realization after logical validation and allocation. The current `dense-no-reuse-v1`
allocation policy remains deliberately independent from these future choices.

## References

1. Y. Cho et al., ["Direct pulse-level compilation of arbitrary quantum logic gates on superconducting qutrits"](https://doi.org/10.1103/PhysRevApplied.22.034066), *Physical Review Applied* 22, 034066 (2024), DOI: 10.1103/PhysRevApplied.22.034066, consulted 2026-08-06.
2. Z. Chen et al., ["Efficient implementation of arbitrary two-qubit gates using unified control"](https://doi.org/10.1038/s41567-025-02990-x), *Nature Physics* 21, 1489-1496 (2025), DOI: 10.1038/s41567-025-02990-x, consulted 2026-08-06.
3. Y. Peng, J. Young, P. Liu, and X. Wu, ["SimuQ: A Framework for Programming Quantum Hamiltonian Simulation with Analog Compilation"](https://arxiv.org/abs/2303.02775), *Proceedings of the ACM on Programming Languages* / POPL 2024, DOI: 10.1145/3632923, consulted 2026-08-06.
4. M. Garcia de Andoin, T. Mueller, and G. Camacho, ["Hamiltonian simulation with explicit formulas for digital-analog quantum computing"](https://doi.org/10.1103/nzxg-5lbg), *Physical Review A* 113, 062607 (2026), DOI: 10.1103/nzxg-5lbg; [open preprint](https://arxiv.org/abs/2511.11404), consulted 2026-08-06.
5. A. Hoyt et al., ["QASMTrans: An End-to-End QASM Compilation Framework with Pulse Generation for Near-Term Quantum Devices"](https://arxiv.org/abs/2602.05154), arXiv:2602.05154 (2026), preprint, consulted 2026-08-06.
6. L. Li et al., ["A Verified Compiler for Quantum Simulation"](https://arxiv.org/abs/2509.18583), arXiv:2509.18583 (2025), preprint, consulted 2026-08-06.
