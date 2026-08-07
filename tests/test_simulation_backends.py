from __future__ import annotations

import unittest
from math import pi

from ariadion import Bit, Qubit, quantum, x
from ariadion_core import IrOperationId, ProgramId
from ariadion_ir import CircuitIR, OpCode, Operation
from ariadion_noise import (
    AmplitudeDampingChannel,
    BinaryReadoutChannel,
    BitFlipChannel,
    DepolarizingChannel,
    ExecutableNoiseModel,
    GateChannelBinding,
    OneQubitGate,
    PhaseDampingChannel,
    PhaseFlipChannel,
)
from ariadion_runtime.runtime import _density_classical_output_distributions
from ariadion_simulator import (
    DensityMatrixExecutionRequest,
    KernelMetadata,
    OperatorStructure,
    ReferenceDensityMatrixBackend,
    ReferenceSampledTrajectoryBackend,
    ReferenceStateVectorBackend,
    SampledExecutionRequest,
    SimulationPlan,
    SimulationQuery,
    StateRepresentation,
    execute_with_backend,
    kernel_metadata_for_operation,
    simulate,
    simulate_density_matrix,
)

try:
    from ariadion_simulator_numpy import (
        NUMPY_COMPLEX_DTYPE,
        NumpyDensityMatrixBackend,
        NumpyStateVectorBackend,
    )

    HAS_NUMPY_SIMULATOR = True
except ModuleNotFoundError:  # pragma: no cover - exercised in dependency-minimal CI
    NUMPY_COMPLEX_DTYPE = None  # type: ignore[assignment]
    NumpyDensityMatrixBackend = None  # type: ignore[assignment]
    NumpyStateVectorBackend = None  # type: ignore[assignment]
    HAS_NUMPY_SIMULATOR = False
from daidalon import compile_logical_module


@quantum
def _reported_one() -> Bit:
    qubit = Qubit()
    x(qubit)
    return qubit


def _operation(
    opcode: OpCode,
    target: int,
    name: str,
    *,
    control: int | None = None,
    angle_radians: float | None = None,
) -> Operation:
    return Operation(
        opcode,
        (target,),
        IrOperationId(f"backend:{name}"),
        controls=() if control is None else (control,),
        angle_radians=angle_radians,
    )


def _circuit(name: str, width: int, *operations: Operation) -> CircuitIR:
    return CircuitIR(ProgramId(f"backend:{name}"), name, width, tuple(operations))


class SimulationBackendContractTests(unittest.TestCase):
    def test_plans_and_kernel_metadata_require_inspectable_evidence(self) -> None:
        with self.assertRaisesRegex(ValueError, "non-empty tuple"):
            SimulationPlan(
                backend_id="test-backend",
                representation=StateRepresentation.STATE_VECTOR,
                query=SimulationQuery.FULL_STATE,
            )
        with self.assertRaisesRegex(ValueError, "non-empty string"):
            KernelMetadata(
                operation_id=IrOperationId(""),
                structure=OperatorStructure.LOCAL_DENSE,
                detail="test local kernel",
            )

    def test_reference_backends_are_explicit_and_report_capability_plans(self) -> None:
        circuit = _circuit("reference-plan", 1, _operation(OpCode.H, 0, "reference-plan-h"))

        state_execution = execute_with_backend(ReferenceStateVectorBackend(), circuit)
        self.assertEqual(state_execution.plan.backend_id, "reference-state-vector")
        self.assertEqual(state_execution.plan.representation, StateRepresentation.STATE_VECTOR)
        self.assertEqual(state_execution.plan.query, SimulationQuery.FULL_STATE)
        self.assertIn("explicitly selected", state_execution.plan.reasons[0])
        for actual, expected in zip(
            state_execution.result.amplitudes,
            simulate(circuit).amplitudes,
            strict=True,
        ):
            self.assertAlmostEqual(actual.real, expected.real)
            self.assertAlmostEqual(actual.imag, expected.imag)

        sampled_execution = execute_with_backend(
            ReferenceSampledTrajectoryBackend(),
            circuit,
            options=SampledExecutionRequest(shots=2, seed=7),
            query=SimulationQuery.SAMPLES,
        )
        self.assertEqual(sampled_execution.plan.backend_id, "reference-sampled-trajectory")
        self.assertEqual(len(sampled_execution.result.shots), 2)

        density_execution = execute_with_backend(
            ReferenceDensityMatrixBackend(),
            circuit,
            options=DensityMatrixExecutionRequest(),
        )
        self.assertEqual(density_execution.plan.backend_id, "reference-density-matrix")
        self.assertEqual(
            density_execution.plan.representation,
            StateRepresentation.DENSITY_MATRIX,
        )

        with self.assertRaisesRegex(ValueError, "does not support"):
            ReferenceStateVectorBackend().plan(circuit, query=SimulationQuery.SAMPLES)
        if not HAS_NUMPY_SIMULATOR:
            self.skipTest("requires optional NumPy simulator backend")
        assert NumpyStateVectorBackend is not None
        with self.assertRaisesRegex(ValueError, "does not accept execution options"):
            NumpyStateVectorBackend().execute(
                circuit,
                options=DensityMatrixExecutionRequest(),
            )

    def test_operator_structure_metadata_describes_local_kernel_choices(self) -> None:
        cases = (
            (OpCode.X, OperatorStructure.PERMUTATION),
            (OpCode.H, OperatorStructure.LOCAL_DENSE),
            (OpCode.Z, OperatorStructure.DIAGONAL),
            (OpCode.RX, OperatorStructure.LOCAL_DENSE),
            (OpCode.RY, OperatorStructure.LOCAL_DENSE),
            (OpCode.RZ, OperatorStructure.DIAGONAL),
            (OpCode.CX, OperatorStructure.CONTROLLED_PERMUTATION),
            (OpCode.RESET, OperatorStructure.KRAUS_CHANNEL),
        )
        for opcode, expected_structure in cases:
            with self.subTest(opcode=opcode):
                operation = _operation(
                    opcode,
                    1 if opcode is OpCode.CX else 0,
                    f"metadata-{opcode.value.lower()}",
                    control=0 if opcode is OpCode.CX else None,
                    angle_radians=pi / 4 if opcode in {OpCode.RX, OpCode.RY, OpCode.RZ} else None,
                )
                metadata = kernel_metadata_for_operation(operation)
                self.assertEqual(metadata[0].structure, expected_structure)

        noisy = kernel_metadata_for_operation(
            _operation(OpCode.H, 0, "metadata-channel"),
            has_quantum_channel=True,
        )
        self.assertEqual(
            tuple(entry.structure for entry in noisy),
            (OperatorStructure.LOCAL_DENSE, OperatorStructure.KRAUS_CHANNEL),
        )
        self.assertEqual(
            kernel_metadata_for_operation(_operation(OpCode.MEASURE, 0, "metadata-measure")),
            (),
        )


@unittest.skipUnless(HAS_NUMPY_SIMULATOR, "requires optional NumPy simulator backend")
class NumpyBackendParityTests(unittest.TestCase):
    def test_numpy_state_vector_matches_reference_for_local_and_controlled_gates(self) -> None:
        circuits = (
            _circuit("state-x", 1, _operation(OpCode.X, 0, "state-x")),
            _circuit("state-h", 1, _operation(OpCode.H, 0, "state-h")),
            _circuit(
                "state-z",
                1,
                _operation(OpCode.H, 0, "state-z-h"),
                _operation(OpCode.Z, 0, "state-z"),
            ),
            _circuit("state-rx", 1, _operation(OpCode.RX, 0, "state-rx", angle_radians=pi / 3)),
            _circuit("state-ry", 1, _operation(OpCode.RY, 0, "state-ry", angle_radians=pi / 3)),
            _circuit(
                "state-rz",
                1,
                _operation(OpCode.H, 0, "state-rz-h"),
                _operation(OpCode.RZ, 0, "state-rz", angle_radians=pi / 3),
            ),
            _circuit(
                "state-bell",
                2,
                _operation(OpCode.H, 0, "state-bell-h"),
                _operation(OpCode.CX, 1, "state-bell-cx", control=0),
            ),
        )

        backend = NumpyStateVectorBackend()
        assert NUMPY_COMPLEX_DTYPE is not None
        self.assertEqual(NUMPY_COMPLEX_DTYPE.name, "complex128")
        for circuit in circuits:
            with self.subTest(circuit=circuit.name):
                expected = simulate(circuit)
                actual = backend.execute(circuit)
                self.assertIsInstance(actual.amplitudes, tuple)
                self._assert_complex_tuple_almost_equal(actual.amplitudes, expected.amplitudes)
                self._assert_float_tuple_almost_equal(actual.probabilities, expected.probabilities)

    def test_numpy_density_matches_reference_for_ideal_gates_noise_and_reset(self) -> None:
        ideal = _circuit(
            "density-ideal",
            2,
            _operation(OpCode.H, 0, "density-ideal-h"),
            _operation(OpCode.RX, 1, "density-ideal-rx", angle_radians=pi / 5),
            _operation(OpCode.RY, 0, "density-ideal-ry", angle_radians=pi / 7),
            _operation(OpCode.RZ, 1, "density-ideal-rz", angle_radians=pi / 3),
            _operation(OpCode.Z, 0, "density-ideal-z"),
            _operation(OpCode.X, 1, "density-ideal-x"),
            _operation(OpCode.CX, 1, "density-ideal-cx", control=0),
        )
        backend = NumpyDensityMatrixBackend()
        expected = simulate_density_matrix(ideal)
        actual = backend.execute(ideal)
        self.assertIsInstance(actual.density_matrix, tuple)
        self._assert_matrix_almost_equal(actual.density_matrix, expected.density_matrix)
        self._assert_float_tuple_almost_equal(actual.probabilities, expected.probabilities)

        channel_cases = (
            (OneQubitGate.X, OpCode.X, BitFlipChannel(0.3)),
            (OneQubitGate.H, OpCode.H, PhaseFlipChannel(0.3)),
            (OneQubitGate.Z, OpCode.Z, DepolarizingChannel(0.3)),
            (OneQubitGate.RX, OpCode.RX, AmplitudeDampingChannel(0.3)),
            (OneQubitGate.RY, OpCode.RY, PhaseDampingChannel(0.3)),
        )
        for gate, opcode, channel in channel_cases:
            with self.subTest(channel=channel.to_dict()["kind"]):
                circuit = _circuit(
                    f"density-{gate.value}",
                    1,
                    _operation(
                        opcode,
                        0,
                        f"density-{gate.value}",
                        angle_radians=pi / 4 if opcode in {OpCode.RX, OpCode.RY} else None,
                    ),
                )
                request = DensityMatrixExecutionRequest(
                    ExecutableNoiseModel(
                        gate_channels=(GateChannelBinding(gate, channel),)
                    )
                )
                expected = simulate_density_matrix(circuit, execution=request)
                actual = backend.execute(circuit, options=request)
                self._assert_matrix_almost_equal(actual.density_matrix, expected.density_matrix)

        reset = _circuit(
            "density-reset",
            2,
            _operation(OpCode.H, 0, "density-reset-h"),
            _operation(OpCode.CX, 1, "density-reset-cx", control=0),
            _operation(OpCode.RESET, 0, "density-reset-reset"),
        )
        expected_reset = simulate_density_matrix(reset)
        actual_reset = backend.execute(reset)
        self._assert_matrix_almost_equal(
            actual_reset.density_matrix,
            expected_reset.density_matrix,
        )

    def test_numpy_backends_match_reference_across_three_qubit_axes(self) -> None:
        circuit = _circuit(
            "three-qubit-axes",
            3,
            _operation(OpCode.H, 2, "three-h"),
            _operation(OpCode.RX, 1, "three-rx", angle_radians=pi / 5),
            _operation(OpCode.RY, 0, "three-ry", angle_radians=-pi / 7),
            _operation(OpCode.CX, 0, "three-cx-upper", control=2),
            _operation(OpCode.Z, 1, "three-z"),
            _operation(OpCode.RZ, 2, "three-rz", angle_radians=pi / 3),
            _operation(OpCode.CX, 1, "three-cx-lower", control=0),
        )

        reference_state = simulate(circuit)
        numpy_state = NumpyStateVectorBackend().execute(circuit)
        self._assert_complex_tuple_almost_equal(
            numpy_state.amplitudes,
            reference_state.amplitudes,
        )

        reference_density = simulate_density_matrix(circuit)
        numpy_density = NumpyDensityMatrixBackend().execute(circuit)
        self._assert_matrix_almost_equal(
            numpy_density.density_matrix,
            reference_density.density_matrix,
        )

        reset_circuit = _circuit(
            "three-qubit-reset",
            3,
            *circuit.operations,
            _operation(OpCode.RESET, 2, "three-reset"),
        )
        reference_reset = simulate_density_matrix(reset_circuit)
        numpy_reset = NumpyDensityMatrixBackend().execute(reset_circuit)
        self._assert_matrix_almost_equal(
            numpy_reset.density_matrix,
            reference_reset.density_matrix,
        )

    def test_numpy_density_result_flows_through_existing_runtime_readout_projection(self) -> None:
        compilation = compile_logical_module(_reported_one.to_logical_module())
        request = DensityMatrixExecutionRequest(
            ExecutableNoiseModel(readout_channel=BinaryReadoutChannel(0.1, 0.25))
        )
        simulation = NumpyDensityMatrixBackend().execute(compilation.ir, options=request)

        physical, reported = _density_classical_output_distributions(
            compilation,
            simulation,
            readout_channel=request.noise_model.readout_channel,
        )
        self.assertIsNotNone(physical)
        self.assertIsNotNone(reported)
        assert physical is not None
        assert reported is not None
        self._assert_float_tuple_almost_equal(physical.probabilities, (0.0, 1.0))
        self._assert_float_tuple_almost_equal(reported.probabilities, (0.25, 0.75))

    def _assert_complex_tuple_almost_equal(
        self,
        actual: tuple[complex, ...],
        expected: tuple[complex, ...],
    ) -> None:
        self.assertEqual(len(actual), len(expected))
        for value, expected_value in zip(actual, expected, strict=True):
            self.assertAlmostEqual(value.real, expected_value.real)
            self.assertAlmostEqual(value.imag, expected_value.imag)

    def _assert_float_tuple_almost_equal(
        self,
        actual: tuple[float, ...],
        expected: tuple[float, ...],
    ) -> None:
        self.assertEqual(len(actual), len(expected))
        for value, expected_value in zip(actual, expected, strict=True):
            self.assertAlmostEqual(value, expected_value)

    def _assert_matrix_almost_equal(
        self,
        actual: tuple[tuple[complex, ...], ...],
        expected: tuple[tuple[complex, ...], ...],
    ) -> None:
        self.assertEqual(len(actual), len(expected))
        for row, expected_row in zip(actual, expected, strict=True):
            self._assert_complex_tuple_almost_equal(row, expected_row)


if __name__ == "__main__":
    unittest.main()
