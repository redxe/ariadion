"""Manual, non-CI comparison of explicit Ariadion simulation backends.

This script reports comparable wall time and modeled state payload bytes. It does
not assert speedups: machine, BLAS, allocator, and NumPy versions all affect the
numbers. Every benchmark names its caller-selected backend; no backend selection
policy is exercised here.
"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import gc
import json
import sys
import time
import tracemalloc
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for source_path in sorted(ROOT.glob("packages/*/src")):
    if source_path.is_dir():
        sys.path.insert(0, str(source_path))

from ariadion_core import IrOperationId, ProgramId
from ariadion_ir import CircuitIR, OpCode, Operation
from ariadion_noise import (
    AmplitudeDampingChannel,
    ExecutableNoiseModel,
    GateChannelBinding,
    OneQubitGate,
)
from ariadion_simulator import (
    DensityMatrixExecutionRequest,
    ReferenceDensityMatrixBackend,
    ReferenceStateVectorBackend,
)

try:
    from ariadion_simulator_numpy import (
        NUMPY_COMPLEX_DTYPE,
        NumpyDensityMatrixBackend,
        NumpyStateVectorBackend,
    )
except ImportError:
    NUMPY_AVAILABLE = False
else:
    NUMPY_AVAILABLE = True


COMPLEX128_BYTES = 16


def _operation(
    opcode: OpCode,
    target: int,
    index: int,
    *,
    control: int | None = None,
    angle_radians: float | None = None,
) -> Operation:
    return Operation(
        opcode,
        (target,),
        IrOperationId(f"benchmark:{index}:{opcode.value.lower()}"),
        controls=() if control is None else (control,),
        angle_radians=angle_radians,
    )


def _circuit(name: str, qubit_count: int, operations: list[Operation]) -> CircuitIR:
    return CircuitIR(
        ProgramId(f"benchmark:{name}:{qubit_count}"),
        name,
        qubit_count,
        tuple(operations),
    )


def _single_h_sweep(qubit_count: int) -> CircuitIR:
    return _circuit(
        "single-h-sweep",
        qubit_count,
        [_operation(OpCode.H, target, target) for target in range(qubit_count)],
    )


def _cx_sweep(qubit_count: int) -> CircuitIR:
    return _circuit(
        "cx-sweep",
        qubit_count,
        [
            _operation(OpCode.CX, target + 1, target, control=target)
            for target in range(max(0, qubit_count - 1))
        ],
    )


def _local_sequence(qubit_count: int) -> CircuitIR:
    operations: list[Operation] = []
    for target in range(qubit_count):
        offset = target * 4
        operations.extend(
            (
                _operation(OpCode.H, target, offset),
                _operation(OpCode.RX, target, offset + 1, angle_radians=0.31),
                _operation(OpCode.RY, target, offset + 2, angle_radians=-0.47),
                _operation(OpCode.RZ, target, offset + 3, angle_radians=0.19),
            )
        )
    return _circuit("local-sequence-no-fusion", qubit_count, operations)


def _density_h(qubit_count: int) -> CircuitIR:
    return _circuit(
        "density-h",
        qubit_count,
        [_operation(OpCode.H, target, target) for target in range(qubit_count)],
    )


def _density_kraus(qubit_count: int) -> CircuitIR:
    return _circuit(
        "density-kraus",
        qubit_count,
        [_operation(OpCode.X, target, target) for target in range(qubit_count)],
    )


def _measure(callable_: Callable[[], object], repetitions: int) -> tuple[float, int]:
    gc.collect()
    tracemalloc.start()
    baseline, _ = tracemalloc.get_traced_memory()
    start = time.perf_counter()
    for _ in range(repetitions):
        callable_()
    elapsed = time.perf_counter() - start
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return elapsed / repetitions, max(0, peak - baseline)


def _emit(
    *,
    name: str,
    backend_id: str,
    dtype: str,
    qubit_count: int,
    state_bytes: int,
    repetitions: int,
    execute: Callable[[], object],
) -> None:
    wall_time_seconds, temporary_python_bytes = _measure(execute, repetitions)
    print(
        json.dumps(
            {
                "backend": backend_id,
                "dtype": dtype,
                "name": name,
                "qubit_count": qubit_count,
                "repetitions": repetitions,
                "state_bytes": state_bytes,
                "temporary_python_bytes": temporary_python_bytes,
                "wall_time_seconds": wall_time_seconds,
            },
            sort_keys=True,
        )
    )


def _run_state_benchmarks(
    *,
    qubit_count: int,
    repetitions: int,
    include_reference: bool,
    include_numpy: bool,
) -> None:
    cases = (
        ("single-h-sweep", _single_h_sweep(qubit_count)),
        ("cx-sweep", _cx_sweep(qubit_count)),
        ("local-sequence-no-fusion", _local_sequence(qubit_count)),
    )
    state_bytes = (1 << qubit_count) * COMPLEX128_BYTES
    if include_reference:
        reference = ReferenceStateVectorBackend()
        for name, circuit in cases:
            _emit(
                name=name,
                backend_id=reference.backend_id,
                dtype="python-complex",
                qubit_count=qubit_count,
                state_bytes=state_bytes,
                repetitions=repetitions,
                execute=lambda circuit=circuit: reference.execute(circuit),
            )
    if include_numpy:
        numpy_backend = NumpyStateVectorBackend()
        for name, circuit in cases:
            _emit(
                name=name,
                backend_id=numpy_backend.backend_id,
                dtype=NUMPY_COMPLEX_DTYPE.name,
                qubit_count=qubit_count,
                state_bytes=state_bytes,
                repetitions=repetitions,
                execute=lambda circuit=circuit: numpy_backend.execute(circuit),
            )


def _run_density_benchmarks(
    *,
    qubit_count: int,
    repetitions: int,
    include_reference: bool,
    include_numpy: bool,
) -> None:
    h_circuit = _density_h(qubit_count)
    kraus_circuit = _density_kraus(qubit_count)
    kraus_request = DensityMatrixExecutionRequest(
        ExecutableNoiseModel(
            gate_channels=(
                GateChannelBinding(OneQubitGate.X, AmplitudeDampingChannel(0.2)),
            )
        )
    )
    cases = (
        ("density-h", h_circuit, DensityMatrixExecutionRequest()),
        ("density-kraus", kraus_circuit, kraus_request),
    )
    state_bytes = (1 << (2 * qubit_count)) * COMPLEX128_BYTES
    if include_reference:
        reference = ReferenceDensityMatrixBackend()
        for name, circuit, request in cases:
            _emit(
                name=name,
                backend_id=reference.backend_id,
                dtype="python-complex",
                qubit_count=qubit_count,
                state_bytes=state_bytes,
                repetitions=repetitions,
                execute=lambda circuit=circuit, request=request: reference.execute(
                    circuit,
                    options=request,
                ),
            )
    if include_numpy:
        numpy_backend = NumpyDensityMatrixBackend()
        for name, circuit, request in cases:
            _emit(
                name=name,
                backend_id=numpy_backend.backend_id,
                dtype=NUMPY_COMPLEX_DTYPE.name,
                qubit_count=qubit_count,
                state_bytes=state_bytes,
                repetitions=repetitions,
                execute=lambda circuit=circuit, request=request: numpy_backend.execute(
                    circuit,
                    options=request,
                ),
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-qubits", type=int, default=12)
    parser.add_argument("--density-qubits", type=int, default=7)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument(
        "--backend",
        choices=("reference", "numpy", "both"),
        default="both",
        help="run explicitly selected reference, NumPy, or both backend implementations",
    )
    arguments = parser.parse_args()
    if arguments.state_qubits < 1 or arguments.density_qubits < 1:
        raise SystemExit("qubit counts must be at least one")
    if arguments.repetitions < 1:
        raise SystemExit("repetitions must be at least one")
    if arguments.backend == "numpy" and not NUMPY_AVAILABLE:
        raise SystemExit("NumPy backend is not installed; install ariadion-simulator-numpy")

    include_reference = arguments.backend in {"reference", "both"}
    include_numpy = arguments.backend in {"numpy", "both"} and NUMPY_AVAILABLE
    if arguments.backend == "both" and not NUMPY_AVAILABLE:
        print("NumPy backend unavailable; running the explicit reference benchmarks only.")
    _run_state_benchmarks(
        qubit_count=arguments.state_qubits,
        repetitions=arguments.repetitions,
        include_reference=include_reference,
        include_numpy=include_numpy,
    )
    _run_density_benchmarks(
        qubit_count=arguments.density_qubits,
        repetitions=arguments.repetitions,
        include_reference=include_reference,
        include_numpy=include_numpy,
    )


if __name__ == "__main__":
    main()
