# Ariadion

**A thread through quantum complexity.**

Ariadion is an early-stage, basis-aware quantum programming platform designed to make quantum programs visible, understandable, and playable. The repository contains a small but working vertical slice:

1. capture a safe subset of a Python quantum function or describe a compatibility builder program;
2. lower it through the **Daidalon** compiler into semantic circuit IR;
3. execute it with reference exact state-vector, sampled-trajectory, or small
  density-matrix simulation;
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

Trace navigation is available through the CLI for files exposing a top-level
`program` builder:

```bash
ariadion run examples/bell.py --trace
ariadion run examples/bell.py --step 1
ariadion debug examples/bell.py
```

The interactive debugger accepts `n` (next), `p` (previous), `g N` (go to a
one-based step), and `q` (quit).

Rotations use explicit source-unit angles and retain canonical radians through
execution and trace rendering:

```python
from ariadion import Program, deg, rad, turns

program = Program(3, name="rotations")
program.rx(0, deg(190))
program.ry(1, rad(2))
program.rz(2, turns(0.25))
```

Bare numeric rotation values are rejected by the compiler so Ariadion never has
to guess their unit.

## Captured quantum functions

Ariadion reads the Python AST of a quantum function. It does not execute the
function body to construct the program. The initial `@quantum` frontend supports
local `Qubit()` declarations, aliases, gate/observation/reset markers, explicit-unit
rotations, and typed terminal returns:

```python
from ariadion import Bit, Qubit, basis, cx, h, quantum, run


@quantum(basis=basis.z)
def bell() -> tuple[Bit, Bit]:
    left = Qubit()
    right = Qubit()
    h(left)
    cx(left, right)
    return left, right


result = run(bell)
```

`result.classical_output_distribution` retains the exact joint Bell distribution:
$00 \,\mapsto\, 0.5$, $01 \,\mapsto\, 0$, $10 \,\mapsto\, 0$, and
$11 \,\mapsto\, 0.5$.

Inferred observation handles ordinary classical returns. Explicit `observe()`
exists when observation timing itself is part of the algorithm:

```python
from ariadion import Bit, Qubit, h, observe, quantum, reset


@quantum
def observe_then_reset() -> Bit:
  value = Qubit()
  h(value)
  result = observe(value)
  reset(value)
  return result
```

`reset(q)` changes the state of the existing managed quantum value to
$|0\rangle$; it does not create a new `Qubit`. Both functions are AST markers and
cannot execute as ordinary Python.

## Exact analysis and sampled trajectories

`run()` remains exact state-vector execution by default. It reports analytical
terminal measurement probabilities and preserves its retained analytical state; it
does not collapse a measurement and rejects a later gate with `A202`. General
`RESET` is rejected in exact pure-state-vector mode with `A203` because an
entangled reset is not a unitary pure-state evolution.

Pass an explicit `SampledExecutionRequest` to execute independent, seeded sampled
trajectories instead:

```python
from ariadion import SampledExecutionRequest, run

sampled = run(bell, execution=SampledExecutionRequest(shots=1_000, seed=42))
assert sampled.classical_output is not None
print(sampled.classical_output.counts)
```

Sampled `MEASURE` produces one outcome and collapses the state before later
operations execute. `RESET` is available only in this sampled IR execution path:
it samples and collapses its target, conditionally applies `X`, and leaves that
target in $|0\rangle$. A reset can disturb correlations with any qubits that were
entangled with the target. Sampled results use distinct public result types and
empirical counts; they do not expose exact probability distributions. A captured
sampled trace describes exactly one trajectory, so trace capture with more than
one shot is rejected with `A204`.

The source markers do not choose execution mode. Running `observe_then_reset`
with default exact state-vector execution raises `A203` for reset, and an exact
quantum operation after `observe()` raises `A202`.

## Exact noisy density matrices

Use `DensityMatrixExecutionRequest` with provider-neutral `OneQubitGate` channel
bindings to execute a small exact mixed-state circuit. The ideal supported gate
runs first, then its matched one-qubit Kraus channel. `CX` is ideal-only in this
first slice.

```python
from ariadion import (
  Bit,
  BitFlipChannel,
  DensityMatrixExecutionRequest,
  ExecutableNoiseModel,
  GateChannelBinding,
  OneQubitGate,
  Qubit,
  quantum,
  run,
  x,
)


@quantum
def noisy_one() -> Bit:
  value = Qubit()
  x(value)
  return value


execution = DensityMatrixExecutionRequest(
  ExecutableNoiseModel(
    gate_channels=(
      GateChannelBinding(OneQubitGate.X, BitFlipChannel(0.1)),
    ),
  )
)
result = run(noisy_one, execution=execution)
```

For logical classical returns, density results expose both
`physical_classical_output_distribution` and
`reported_classical_output_distribution`. A model-level `BinaryReadoutChannel`
changes only the reported distribution, never `result.simulation.density_matrix`.
Exact density observations remain terminal. Density execution supports exact reset,
including entangled targets, but currently rejects enabled amplitude trace capture
with `A205` rather than fabricating state-vector snapshots.

Captured quantum functions can now compose through explicit logical bindings:

```python
from ariadion import Bit, Qubit, cx, h, quantum, run


@quantum
def entangle(left: Qubit, right: Qubit) -> None:
  h(left)
  cx(left, right)


@quantum
def bell() -> tuple[Bit, Bit]:
  left = Qubit()
  right = Qubit()
  entangle(left, right)
  return left, right


result = run(bell)
```

The `entangle(left, right)` call remains a `LogicalCallOperation` rather than
textual substitution. Ariadion binds callee parameters as aliases to `bell`'s
existing logical values, then Daidalon materializes invocation-aware logical
values before allocation:

```text
Python functions -> LogicalModule -> call expansion / logical instantiation
-> ExpandedLogicalProgram -> lifetime and release-safety analysis
-> logical-slot allocation
-> CircuitIR
```

A qubit declaration inside a reusable quantum function is a definition. Each
function invocation instantiates that declaration as a distinct logical quantum
value unless the value is a bound parameter alias. The allocation policy is still
conservative: `expanded-dense-no-reuse-v1` allocates every expanded value to a
dense slot. `peak_semantically_live_values` is source-semantic evidence, while
`peak_live_qubits` is the width actually allocated by the selected policy.

> **Quantum liveness is not quantum reusability. A value may become unreachable
> while its state remains entangled with live values. Reusing its execution slot
> requires a proven-clean state or an explicit discard/reset capability.**

The compiler records separate release evidence for every expanded value. Returned
values and borrowed entry parameters are `retained`; other local values are
`discard_required`. `discard_required` never authorizes slot reuse. The current
allocation policies intentionally remain dense and non-reusing.

Scalar `Qubit` call results are supported through one assignment target:

```python
@quantum
def prepare() -> Qubit:
  value = Qubit()
  h(value)
  return value


@quantum
def use_prepared() -> Qubit:
  value = prepare()
  z(value)
  return value
```

Returning a `Qubit` transfers the same logical quantum value across the function
boundary. It never copies quantum state. A bare call still requires a `None`
return; classical and tuple call results, callee observations, and external
quantum-state injection remain deferred. Generated IR retains the definition
source for a callee operation and a separate structured invocation frame for each
call site.

Rotations retain their written unit and lower to canonical radians without calling
the angle helper as ordinary Python:

```python
from ariadion import Qubit, deg, quantum, run, rx


@quantum
def rotate() -> Qubit:
    target = Qubit()
    rx(target, deg(190))
    return target


result = run(rotate)
```

Quantum parameters are captured as unresolved logical inputs. They are not
silently initialized to $|0\rangle$, so an independently executed function with a
parameter fails with diagnostic code `P113` until a caller composition supplies
that value:

```python
from ariadion import Qubit, deg, quantum, rx


@quantum
def rotate_input(target: Qubit) -> Qubit:
    rx(target, deg(190))
    return target
```

Composition binds only a callee's parameter to an existing caller logical value.
It does not bind parameters of the entry function to external runtime state.

When a trace is inspected, rotation steps also carry a structured explanation:
exact probability, relative-phase, and global-phase facts are separate from a
clearly labeled educational Bloch-sphere interpretation. The CLI renders both
sections, while Studio can consume the same structured data directly.

Or use the modules directly:

```python
from ariadion import Program, TraceCaptureOptions, inspect_execution_trace, run

program = Program(2, name="bell")
program.h(0).cx(0, 1)

result = run(program, trace=TraceCaptureOptions(enabled=True))
print(result.circuit)
print(result.report)

trace = result.trace
assert trace is not None
print(trace.steps[0].after.amplitudes)

trace_inspection = inspect_execution_trace(trace)
print(trace_inspection.steps[0].transition.basis_state_changes)
print(trace_inspection.steps[0].rotation_explanation)
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
  core/            shared identity and source-location contracts
  language/        Python-first program model
  noise/           neutral typed executable noise-channel contracts
  semantics/       pre-allocation logical quantum-value contracts
  frontend-python/ safe valid-Python AST capture into logical semantics
  syntax/          immutable Python-extension source and compatibility AST contracts
  ir/              semantic circuit IR
  daidalon/        compiler and validation passes
  runtime/         orchestration layer
  simulator/       dependency-free state-vector and exact density-matrix simulators
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

See [`docs/architecture.md`](docs/architecture.md), [the object-model design
guide](docs/object-model.md), [the debugger provenance guide](docs/debugger.md),
[`specs/language.md`](specs/language.md), [the
Python-extension syntax specification](specs/syntax.md), [`specs/runtime.md`](specs/runtime.md),
[`specs/inspection.md`](specs/inspection.md), and [`specs/debugger.md`](specs/debugger.md).
