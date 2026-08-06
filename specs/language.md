# Ariadion language model — draft 0

The initial API is embedded in Python. A source program declares a fixed number of qubits and appends explicit operations.

```python
program = Program(2, name="bell")
program.h(0)
program.cx(0, 1)
```

## Current operations

- `x(target)`
- `h(target)`
- `z(target)`
- `cx(control, target)`
- `measure(target, key=None)`

## Invariants

1. Qubit indices are zero-based and must be within the declared program width.
2. A controlled operation may not use the same qubit as control and target.
3. Source-level operations preserve insertion order.
4. Measurement is explicit; simulation reports probabilities without sampling unless sampling is requested by a future API.
5. The compiler, not the source builder, owns semantic validation.

## Basis direction

The next language revision will attach an explicit basis descriptor to preparation, observation, and debugging operations. Basis conversion must appear in IR rather than being inferred by a backend.
