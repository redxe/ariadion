# Ariadion

Ariadion is a Python quantum programming platform that keeps programmer intent as
the stable contract. Quantum programs are expressed in terms of logical qubits and
observable measurements; allocation, compilation, and simulation are handled by the
platform and are replaceable without changing program semantics.

## Status

**0.1.0rc3 — Release Candidate.** Ariadion is in active development. Public APIs
may change before the final 1.0 release. Simulation-only; hardware execution is not
yet available.

## Installation

Ariadion is not yet published to PyPI. Installation from a local build is possible
once release engineering is complete. See the
[repository](https://github.com/redxe/ariadion) for current status.

## Capabilities

- Logical qubit programming with a Python-native syntax
- Exact state-vector and density-matrix simulation
- Sampled and deterministic execution modes
- Noise-channel modeling with provider-neutral contracts
- Noise-impact, bare-reliability, and protection-requirement reporting
- Optional [NumPy](https://numpy.org/) complex128 backend for numerical validation
- Trace inspection and structured debugger output

## Quick example

```python
from ariadion import Program, run

program = Program(2, name="bell")
program.h(0).cx(0, 1)
result = run(program)
print(result.simulation.probabilities)  # [0.5, 0.0, 0.0, 0.5]
```

## License

Apache-2.0 — see [LICENSE](https://github.com/redxe/ariadion/blob/main/LICENSE).

## Links

- [Repository](https://github.com/redxe/ariadion)
- [Issues](https://github.com/redxe/ariadion/issues)
- [Changelog](https://github.com/redxe/ariadion/blob/main/CHANGELOG.md)
