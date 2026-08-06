# Trace debugger contract — draft 0

The trace debugger is a frontend-neutral projection over an immutable
`ExecutionTrace` and its separately requested `TraceInspection`. It does not
simulate a program, mutate a trace, or own terminal input.

## Structured view model

`TraceDebuggerSession` combines a `CircuitIR`, an `ExecutionTrace`, and a
matching `TraceInspection`. It validates matching circuit IDs, trace schema
versions, contiguous step indexes, and IR operation IDs before exposing a view.
It is immutable: `next()`, `previous()`, and `go_to()` return a new session.

`TraceStepViewModel` describes one active operation for any frontend. It exposes:

- the source operation, IR operation ID, source reference, and compiler
  provenance;
- the canonical rotation angle and preserved source-unit metadata when applicable;
- the circuit and zero-based active operation index for synchronized rendering;
- before and after Theonoe state reports;
- basis-state probability and relative-phase changes;
- entanglement changes and any unobservable global-phase delta;
- an optional structured rotation explanation with exact trace facts and a
  separately labeled educational interpretation;
- exact measurement data and its execution kind when the operation measures qubits;
- lowered observation metadata (declared result ID, logical qubit ID, basis, and
  reason) when available.

`TraceStepViewModel` has `to_dict()` and canonical `to_json()` output for an
individual active step. `TraceDebuggerSession` serializes a complete debugger
document with its own `schema_version`, `current_step_index`, the complete
serialized `CircuitIR`, `ExecutionTrace`, and `TraceInspection`. Studio can
reconstruct the whole circuit and every inspected operation directly from that
document instead of scraping terminal text.

The session validates every inspection step against the matching trace operation:
operation ID, opcode, targets, controls, key, observation metadata, source,
compiler provenance, and measurement record must agree. This prevents a UI from
combining Theonoe analysis with metadata from a different operation.

## CLI behavior

The first CLI debugger supports:

```text
ariadion run PROGRAM.py --trace
ariadion run PROGRAM.py --step N
ariadion debug PROGRAM.py
```

`--step N` uses one-based step numbers for people, while runtime trace indexes
remain zero-based. `--trace` renders every step. `debug` accepts `n` for next,
`p` for previous, `g N` to go to a one-based step number, and `q` to quit.

A program file must expose a top-level `Program` named `program`. Files that also
print a standalone result should place that behavior under
`if __name__ == "__main__":` so the CLI can load the builder without executing
its own presentation code.

## Rendering boundary

`ariadion_cli.trace_view.render_trace_step()` accepts only a
`TraceStepViewModel`. It renders a circuit with the active gate highlighted,
visible before/after basis states, probability and relative-phase changes,
unobservable global phase when nonzero, entanglement changes, measurement
probabilities, observation metadata, source data, compiler provenance, and
precomputed rotation explanations. An `exact_terminal_distribution` is visibly
labeled as an analytical projection with an unchanged retained state; it is not
rendered as a sampled collapse. Rotation rendering labels exact facts separately
from educational interpretations. Terminal command parsing and input remain outside
this rendering function.

Measurement output carries the runtime `targets_lsb_first` convention: target
`targets[i]` maps to outcome bit `i`. See the runtime trace contract for the
complete measurement-bit ordering definition.
