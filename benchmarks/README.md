# Benchmarks

`simulation_kernels.py` is a manual, non-CI benchmark for the explicit reference
and optional NumPy CPU simulation backends. It covers a single-`H` sweep, a `CX`
sweep, a small local sequence without gate fusion, density `H`, and density Kraus
workloads.

Run it from the repository root after making the relevant packages available to
the Python environment:

```text
python benchmarks/simulation_kernels.py --backend both
```

Each line is JSON with the explicitly selected backend, dtype, qubit count, mean
wall time, modeled state payload bytes, and `tracemalloc`'s Python-allocation peak
delta. The allocation value is not a full native-memory measurement, so it must not
be interpreted as the total temporary memory used by NumPy or a future accelerator.
The script deliberately contains no timing threshold or performance assertion.
