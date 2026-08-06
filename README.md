# Ariadion

**A thread through quantum complexity.**

Ariadion is an early-stage, basis-aware quantum programming platform designed to make quantum programs visible, understandable, and playable. The repository contains a small but working vertical slice:

1. describe a quantum program with a Python-first API;
2. lower it through the **Daidalon** compiler into semantic circuit IR;
3. execute it with the reference state-vector simulator;
4. inspect amplitudes, probabilities, phase, and entanglement hints with **Theonoe**;
5. render a synchronized ASCII circuit view.

> Status: foundation / pre-alpha. APIs are intentionally small and expected to evolve.

## Naming

- **Ariadion** — the platform, language, runtime, and public SDK. Inspired by Ariadne's thread through the Labyrinth.
- **Daidalon** — the compiler and synthesis engine. Inspired by Daedalus, the legendary builder.
- **Theonoe** — the debugger and state-inspection engine. Named for the prophetic figure associated with hidden knowledge.

## Quick start

No third-party runtime dependencies are required for the current reference implementation.

```bash
python tools/run_example.py examples/bell.py
python tools/test.py
```

Or use the modules directly:

```python
from ariadion import Program, run

program = Program(2, name="bell")
program.h(0).cx(0, 1)

result = run(program)
print(result.circuit)
print(result.report)
```

Expected probabilities:

```text
|00>  0.500000
|11>  0.500000
```

## Repository map

```text
packages/
  sdk/             Ariadion public facade
  language/        Python-first program model
  ir/              semantic circuit IR
  daidalon/        compiler and validation passes
  runtime/         orchestration layer
  simulator/       dependency-free state-vector reference simulator
  theonoe/         debugger and state inspector
  visualization/   circuit/state renderers
apps/
  cli/             command-line shell
  studio/          IDE product shell and design notes
specs/              language and IR contracts
docs/               architecture, naming, and roadmap
examples/            runnable programs
tests/               vertical-slice tests
```

## Design principles

- **Python-simple:** useful programs should read like ordinary Python.
- **Quantum-explicit:** basis, phase, measurement, and ownership semantics should never be silently guessed.
- **Visible by default:** every compilation and execution artifact should be inspectable.
- **Provider-neutral:** semantic IR sits between source code and simulator or hardware backends.
- **Teach through execution:** tutorials and diagnostics should use the same runtime as real projects.

See [`docs/architecture.md`](docs/architecture.md) and [`specs/language.md`](specs/language.md).
