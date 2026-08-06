# Semantic IR — draft 0

`CircuitIR` is immutable and provider-neutral.

```text
CircuitIR
  name: str
  qubit_count: int
  operations: tuple[Operation, ...]
```

Each `Operation` contains:

- an opcode;
- ordered target qubits;
- optional control qubits;
- optional classical key;
- optional source metadata.

The current opcodes are `X`, `H`, `Z`, `CX`, and `MEASURE`.

Future revisions will add basis descriptors, parameters, classical values, regions, ownership metadata, and decomposition provenance.
