# Persistent computation artifacts design evidence

**Documentation consulted:** 2026-08-07.

This record preserves deferred architecture research for persistence and
out-of-core directions. It is design evidence only. Ariadion has no accepted
implementation ADR for this work in the current milestone sequence.

## Scope and status

The current Ariadion stack is optimized for transparent in-memory execution
artifacts. Persistence is a separate design axis and must remain explicit.

This note distinguishes four concerns that are often conflated:

1. reproducibility and provenance artifacts,
2. deterministic computation caching,
3. checkpoint and restart artifacts,
4. out-of-core numerical execution.

These concerns overlap operationally, but they are not interchangeable and must
remain separately modeled.

## Engineering claim: use different storage forms for metadata versus large states

SQLite's internal-versus-external BLOB guidance explains that large binary data
can be better managed outside SQL rows depending on payload size and access
behavior. See [SQLite internal vs external BLOB guidance](https://sqlite.org/intern-v-extern-blob.html).

Bazel's remote cache design separates content-addressed artifacts from action
metadata and dependency keys. See [Bazel remote caching](https://bazel.build/remote/caching).

NumPy documentation explicitly covers memory mapping for large arrays and I/O
trade-offs. See [NumPy I/O and memory mapping guidance](https://numpy.org/doc/stable/user/how-to-io.html).

Zarr v3 specifies chunked, key-addressable array storage suitable for local or
object-store style backends. See [Zarr v3 core specification](https://zarr-specs.readthedocs.io/en/latest/v3/core/index.html).

**Ariadion recommendation (deferred):**

- use SQLite (or an equivalent embedded database) for searchable metadata,
  artifact relationships, lineage, and query indexes,
- use content-addressed files or object storage for large immutable artifacts,
- use canonical JSON for small typed reports and interoperability,
- allow NumPy memory mapping as a local experiment path,
- evaluate Zarr or equivalent chunked storage for later distributed/object-store
  use.

**Explicit rejection:** do not store individual amplitudes or giant matrices as
SQL rows.

## Quantitative scaling evidence and limits

For `complex128` values:

- state vector bytes: $16 \times 2^n$,
- density matrix bytes: $16 \times 4^n$.

Examples:

- $n=30$ state vector: $16 \times 2^{30}$ bytes $= 16$ GiB,
- $n=15$ density matrix: $16 \times 4^{15}$ bytes $= 16$ GiB,
- $n=20$ density matrix: $16 \times 4^{20}$ bytes $= 16$ TiB.

Secondary storage can extend effective capacity and recovery options, but it
does not remove exponential scaling.

Trace overhead depends on capture policy and retained fields. It must not be
universalized as exactly two complete state vectors per step unless that explicit
full before/after trace mode is selected.

## Current Ariadion implementation evidence (not permanent invariants)

The current reference simulator tuple-materializes full outputs and trace
snapshots:

- `SimulationResult(circuit, tuple(state))` appears in
  `packages/simulator/src/ariadion_simulator/statevector.py`.
- trace capture stores `before_amplitudes=tuple(state)` and
  `after_amplitudes=tuple(state)` in the same file.

The current NumPy backend also returns Python tuples from full arrays:

- `SimulationResult(circuit, tuple(complex(value) for value in state))` in
  `packages/simulator-numpy/src/ariadion_simulator_numpy/backends.py`.

Runtime trace projection currently retains complete before/after snapshots:

- `_trace_step_from_capture(...)` constructs `StateSnapshot(...)` from
  `captured_step.before_amplitudes` and `captured_step.after_amplitudes` in
  `packages/runtime/src/ariadion_runtime/trace.py`.

These are current implementation facts, not fixed architecture law.

**Deferred implication:** an out-of-core simulator must expose an explicit
lazy/query-oriented result contract or artifact-handle contract. It must not
silently reuse a fully tuple-materializing result path.

## Durable cache identity requirements

Reusable deterministic cache entries must include at least:

- schema version,
- canonical program or IR fingerprint,
- compiler and allocation policy plus version,
- backend identity and backend implementation version,
- execution mode or query,
- schedule identity,
- noise and readout model identity,
- dtype and byte ordering,
- tolerances or approximation budget,
- seed and shots when stochastic execution applies,
- relevant code version.

## Scientific safety invariants

- cache presence cannot alter scientific meaning,
- corruption or incompatibility becomes a safe cache miss,
- stochastic reuse is valid only with complete matching execution identity,
- lossy storage requires an explicit approximation contract,
- logical or semantic identity must not depend on storage location,
- persistence must not introduce hidden runtime side effects.

## Future-use mapping (deferred)

- protection planning: persist candidate evaluations and Pareto evidence for
  reproducible planner decisions,
- Milestone 6: streamed or lazy trace views and restart checkpoints,
- Milestone 7: Studio project history, reproducible Capsules, and artifact
  inspection surfaces,
- Milestone 8: durable distributed jobs, restart flows, and object-storage
  backing,
- out-of-core simulation remains an explicit experimental backend choice.

## Large-number analogy and limits

Block-aware memory movement matters in classical large-scale kernels. See
[cache-oblivious FFT and matrix multiplication notes](https://ocw.mit.edu/courses/6-895-theory-of-parallel-systems-sma-5509-fall-2003/6dc7de52dcf13b53cebf2fe10ae6752a_cach_oblvs_thsis.pdf).

Large prime search systems demonstrate operational value from durable work
records, checkpointing, and verifiable proof artifacts. See
[GIMPS project documentation](https://www.mersenne.org/).

Persistence can improve reuse, failure recovery, capacity management, and
verification workflows without changing the underlying asymptotic complexity of
the numerical problem.

## Related simulation research context

Out-of-core and decomposition strategies depend on representation and workload.
They are not generic guarantees for arbitrary quantum states:

- [QDAO](https://ieeexplore.ieee.org/document/10323666/) studies out-of-core data movement for quantum circuit simulation,
- [Tensor contraction and deferred execution context](https://arxiv.org/abs/1710.05867),
- [RosneT](https://arxiv.org/abs/2201.06620) on distributed tensor-network simulation,
- [Stabilizer simulation](https://arxiv.org/abs/quant-ph/0406196) for Clifford-restricted circuits,
- [Limited-entanglement/MPS simulation](https://doi.org/10.1103/PhysRevLett.91.147902),
- [Tensor contraction planning](https://quantum-journal.org/papers/q-2021-03-15-410/).

These sources support a layered strategy: select specialized or approximate
backends explicitly when their assumptions hold, rather than claiming universal
compression or claiming that storage hardware removes exponential behavior.

## References

1. [NumPy I/O and memory mapping guidance](https://numpy.org/doc/stable/user/how-to-io.html), official technical documentation, consulted 2026-08-07.
2. [Zarr v3 core specification](https://zarr-specs.readthedocs.io/en/latest/v3/core/index.html), official technical documentation, consulted 2026-08-07.
3. [SQLite internal versus external BLOB guidance](https://sqlite.org/intern-v-extern-blob.html), official technical documentation, consulted 2026-08-07.
4. [Bazel remote caching](https://bazel.build/remote/caching), official technical documentation, consulted 2026-08-07.
5. [QDAO](https://ieeexplore.ieee.org/document/10323666/), IEEE record, consulted 2026-08-07.
6. [Tensor contraction deferral context](https://arxiv.org/abs/1710.05867), arXiv:1710.05867, consulted 2026-08-07.
7. [RosneT](https://arxiv.org/abs/2201.06620), arXiv:2201.06620, consulted 2026-08-07.
8. [Cache-oblivious FFT and matrix multiplication notes](https://ocw.mit.edu/courses/6-895-theory-of-parallel-systems-sma-5509-fall-2003/6dc7de52dcf13b53cebf2fe10ae6752a_cach_oblvs_thsis.pdf), lecture notes, consulted 2026-08-07.
9. [Stabilizer simulation](https://arxiv.org/abs/quant-ph/0406196), arXiv:quant-ph/0406196, consulted 2026-08-07.
10. [Limited-entanglement/MPS simulation](https://doi.org/10.1103/PhysRevLett.91.147902), Physical Review Letters 91, 147902, consulted 2026-08-07.
11. [Tensor contraction planning](https://quantum-journal.org/papers/q-2021-03-15-410/), Quantum 5, 410, consulted 2026-08-07.
12. [GIMPS project documentation](https://www.mersenne.org/), consulted 2026-08-07.
