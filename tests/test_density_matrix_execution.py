from __future__ import annotations

import unittest
from math import pi

from ariadion import Bit, Qubit, observe, quantum, run, x
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
    QuantumChannel,
    QuantumChannelValidationError,
)
from ariadion_runtime import (
    DensityMatrixLogicalRunResult,
    DensityMatrixRunResult,
    DensityMatrixTraceUnsupportedError,
    TraceCaptureOptions,
)
from ariadion_semantics import EvolutionModel, NoiseFeature, NoiseModelOrigin, SimulationRequest
from ariadion_simulator import (
    DENSITY_MATRIX_POSITIVITY_ABS_TOLERANCE,
    DensityMatrixExecutionRequest,
    DensityMatrixInvariantError,
    DensityMatrixResult,
    DensityMatrixTerminalObservationError,
    simulate,
    simulate_density_matrix,
)


@quantum
def _reported_one() -> Bit:
    qubit = Qubit()
    x(qubit)
    return qubit


@quantum
def _reported_zero_pair() -> tuple[Bit, Bit]:
    left = Qubit()
    right = Qubit()
    return left, right


@quantum
def _reported_alias() -> tuple[Bit, Bit]:
    qubit = Qubit()
    outcome = observe(qubit)
    return outcome, outcome


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
        IrOperationId(f"density:{name}"),
        controls=() if control is None else (control,),
        angle_radians=angle_radians,
    )


def _circuit(name: str, width: int, *operations: Operation) -> CircuitIR:
    return CircuitIR(
        ProgramId(f"density:{name}"),
        name,
        width,
        tuple(operations),
    )


class _InvalidKrausChannel(QuantumChannel):
    def kraus_operators(
        self,
    ) -> tuple[tuple[tuple[complex, complex], tuple[complex, complex]], ...]:
        return (((2 + 0j, 0j), (0j, 2 + 0j)),)

    def to_dict(self) -> dict[str, object]:
        return {"kind": "invalid"}


class DensityMatrixExecutionTests(unittest.TestCase):
    def test_zero_initialization_and_result_invariants(self) -> None:
        circuit = _circuit("zero", 1)

        result = simulate_density_matrix(circuit)

        self.assertEqual(result.density_matrix, ((1 + 0j, 0j), (0j, 0j)))
        self.assertEqual(result.probabilities, (1.0, 0.0))
        with self.assertRaises(DensityMatrixInvariantError):
            DensityMatrixResult(circuit, ((1 + 0j,),))
        with self.assertRaises(DensityMatrixInvariantError):
            DensityMatrixResult(
                circuit,
                ((1 + 0j, 1 + 0j), (0j, 0j)),
            )
        with self.assertRaises(DensityMatrixInvariantError):
            DensityMatrixResult(circuit, ((2 + 0j, 0j), (0j, 0j)))

    def test_density_result_rejects_materially_negative_eigenvalues(self) -> None:
        circuit = _circuit("nonphysical", 1)

        with self.assertRaisesRegex(DensityMatrixInvariantError, "positive semidefinite"):
            DensityMatrixResult(
                circuit,
                ((0.5 + 0j, 0.6 + 0j), (0.6 + 0j, 0.5 + 0j)),
            )

        tolerance_scale = DENSITY_MATRIX_POSITIVITY_ABS_TOLERANCE / 2
        accepted = DensityMatrixResult(
            circuit,
            ((1 + tolerance_scale + 0j, 0j), (0j, -tolerance_scale + 0j)),
        )
        self.assertEqual(accepted.circuit, circuit)

    def test_density_result_accepts_valid_pure_and_mixed_states(self) -> None:
        circuit = _circuit("physical", 1)

        pure = DensityMatrixResult(
            circuit,
            ((0.5 + 0j, 0.5 + 0j), (0.5 + 0j, 0.5 + 0j)),
        )
        mixed = DensityMatrixResult(
            circuit,
            ((0.5 + 0j, 0j), (0j, 0.5 + 0j)),
        )

        self.assertEqual(pure.probabilities, (0.5, 0.5))
        self.assertEqual(mixed.probabilities, (0.5, 0.5))

    def test_all_supported_ideal_single_qubit_gates_evolve_density(self) -> None:
        cases = (
            (OpCode.X, None, ((0j, 0j), (0j, 1 + 0j))),
            (OpCode.H, None, ((0.5 + 0j, 0.5 + 0j), (0.5 + 0j, 0.5 + 0j))),
            (OpCode.Z, None, ((1 + 0j, 0j), (0j, 0j))),
            (OpCode.RX, pi, ((0j, 0j), (0j, 1 + 0j))),
            (OpCode.RY, pi, ((0j, 0j), (0j, 1 + 0j))),
            (OpCode.RZ, pi, ((1 + 0j, 0j), (0j, 0j))),
        )
        for opcode, angle_radians, expected in cases:
            with self.subTest(opcode=opcode):
                result = simulate_density_matrix(
                    _circuit(
                        f"ideal-{opcode.value.lower()}",
                        1,
                        _operation(
                            opcode,
                            0,
                            f"ideal-{opcode.value.lower()}",
                            angle_radians=angle_radians,
                        ),
                    )
                )
                self._assert_matrix_almost_equal(result.density_matrix, expected)

    def test_ideal_h_and_bell_cx_match_expected_exact_density(self) -> None:
        h_result = simulate_density_matrix(
            _circuit("h", 1, _operation(OpCode.H, 0, "h"))
        )
        self._assert_matrix_almost_equal(
            h_result.density_matrix,
            ((0.5 + 0j, 0.5 + 0j), (0.5 + 0j, 0.5 + 0j)),
        )

        bell = simulate_density_matrix(
            _circuit(
                "bell",
                2,
                _operation(OpCode.H, 0, "bell-h"),
                _operation(OpCode.CX, 1, "bell-cx", control=0),
            )
        )
        self._assert_matrix_almost_equal(
            bell.density_matrix,
            (
                (0.5 + 0j, 0j, 0j, 0.5 + 0j),
                (0j, 0j, 0j, 0j),
                (0j, 0j, 0j, 0j),
                (0.5 + 0j, 0j, 0j, 0.5 + 0j),
            ),
        )

    def test_zero_noise_density_equals_state_vector_outer_product(self) -> None:
        circuit = _circuit(
            "pure-equivalence",
            2,
            _operation(OpCode.H, 0, "pure-h"),
            _operation(OpCode.RY, 1, "pure-ry", angle_radians=pi / 3),
            _operation(OpCode.CX, 1, "pure-cx", control=0),
        )

        density = simulate_density_matrix(circuit)
        vector = simulate(circuit)
        expected = tuple(
            tuple(amplitude * other.conjugate() for other in vector.amplitudes)
            for amplitude in vector.amplitudes
        )

        self._assert_matrix_almost_equal(density.density_matrix, expected)

    def test_configured_channels_apply_after_their_matching_ideal_gate(self) -> None:
        bit_flipped = simulate_density_matrix(
            _circuit("bit-flip", 1, _operation(OpCode.X, 0, "bit-flip-x")),
            execution=DensityMatrixExecutionRequest(
                ExecutableNoiseModel(
                    gate_channels=(
                        GateChannelBinding(OneQubitGate.X, BitFlipChannel(1.0)),
                    )
                )
            ),
        )
        self.assertEqual(bit_flipped.density_matrix, ((1 + 0j, 0j), (0j, 0j)))

        phase_flipped = simulate_density_matrix(
            _circuit("phase-flip", 1, _operation(OpCode.H, 0, "phase-flip-h")),
            execution=DensityMatrixExecutionRequest(
                ExecutableNoiseModel(
                    gate_channels=(
                        GateChannelBinding(OneQubitGate.H, PhaseFlipChannel(1.0)),
                    )
                )
            ),
        )
        self._assert_matrix_almost_equal(
            phase_flipped.density_matrix,
            ((0.5 + 0j, -0.5 + 0j), (-0.5 + 0j, 0.5 + 0j)),
        )

        depolarized = simulate_density_matrix(
            _circuit("depolarizing", 1, _operation(OpCode.H, 0, "depolarizing-h")),
            execution=DensityMatrixExecutionRequest(
                ExecutableNoiseModel(
                    gate_channels=(
                        GateChannelBinding(
                            OneQubitGate.H,
                            DepolarizingChannel(1.0),
                        ),
                    )
                )
            ),
        )
        self.assertAlmostEqual(depolarized.density_matrix[0][0].real, 0.5)
        self.assertAlmostEqual(depolarized.density_matrix[1][1].real, 0.5)
        self.assertAlmostEqual(depolarized.density_matrix[0][1].real, -1 / 6)

    def test_amplitude_and_phase_damping_apply_their_documented_kraus_maps(self) -> None:
        amplitude_damped = simulate_density_matrix(
            _circuit("amplitude", 1, _operation(OpCode.X, 0, "amplitude-x")),
            execution=DensityMatrixExecutionRequest(
                ExecutableNoiseModel(
                    gate_channels=(
                        GateChannelBinding(
                            OneQubitGate.X,
                            AmplitudeDampingChannel(1.0),
                        ),
                    )
                )
            ),
        )
        self.assertEqual(amplitude_damped.density_matrix, ((1 + 0j, 0j), (0j, 0j)))

        phase_damped = simulate_density_matrix(
            _circuit("phase-damping", 1, _operation(OpCode.H, 0, "phase-damping-h")),
            execution=DensityMatrixExecutionRequest(
                ExecutableNoiseModel(
                    gate_channels=(
                        GateChannelBinding(
                            OneQubitGate.H,
                            PhaseDampingChannel(0.75),
                        ),
                    )
                )
            ),
        )
        self.assertAlmostEqual(phase_damped.density_matrix[0][0].real, 0.5)
        self.assertAlmostEqual(phase_damped.density_matrix[1][1].real, 0.5)
        self.assertAlmostEqual(phase_damped.density_matrix[0][1].real, 0.25)

    def test_trace_remains_one_for_each_supported_channel(self) -> None:
        channel_cases = (
            (OneQubitGate.X, OpCode.X, BitFlipChannel(0.3)),
            (OneQubitGate.H, OpCode.H, PhaseFlipChannel(0.3)),
            (OneQubitGate.Z, OpCode.Z, DepolarizingChannel(0.3)),
            (OneQubitGate.RX, OpCode.RX, AmplitudeDampingChannel(0.3)),
            (OneQubitGate.RY, OpCode.RY, PhaseDampingChannel(0.3)),
        )
        for gate, opcode, channel in channel_cases:
            with self.subTest(channel=channel.to_dict()["kind"]):
                result = simulate_density_matrix(
                    _circuit(
                        f"trace-{gate.value}",
                        1,
                        _operation(
                            opcode,
                            0,
                            f"trace-{gate.value}",
                            angle_radians=pi / 4 if opcode in {OpCode.RX, OpCode.RY} else None,
                        ),
                    ),
                    execution=DensityMatrixExecutionRequest(
                        ExecutableNoiseModel(
                            gate_channels=(GateChannelBinding(gate, channel),)
                        )
                    ),
                )
                self.assertAlmostEqual(sum(result.probabilities), 1.0)

    def test_invalid_custom_kraus_channels_are_rejected_before_execution(self) -> None:
        request = DensityMatrixExecutionRequest(
            ExecutableNoiseModel(
                gate_channels=(
                    GateChannelBinding(OneQubitGate.X, _InvalidKrausChannel()),
                )
            )
        )

        with self.assertRaises(QuantumChannelValidationError):
            simulate_density_matrix(
                _circuit("invalid-kraus", 1, _operation(OpCode.X, 0, "invalid-kraus-x")),
                execution=request,
            )

    def test_exact_density_reset_handles_an_entangled_target(self) -> None:
        result = simulate_density_matrix(
            _circuit(
                "reset-bell",
                2,
                _operation(OpCode.H, 0, "reset-bell-h"),
                _operation(OpCode.CX, 1, "reset-bell-cx", control=0),
                _operation(OpCode.RESET, 0, "reset-bell-reset"),
                _operation(OpCode.MEASURE, 0, "reset-bell-measure-left"),
                _operation(OpCode.MEASURE, 1, "reset-bell-measure-right"),
            )
        )

        self._assert_matrix_almost_equal(
            result.density_matrix,
            (
                (0.5 + 0j, 0j, 0j, 0j),
                (0j, 0j, 0j, 0j),
                (0j, 0j, 0.5 + 0j, 0j),
                (0j, 0j, 0j, 0j),
            ),
        )
        self.assertAlmostEqual(result.probabilities[0], 0.5)
        self.assertEqual(result.probabilities[1], 0.0)
        self.assertAlmostEqual(result.probabilities[2], 0.5)
        self.assertEqual(result.probabilities[3], 0.0)

    def test_density_observations_are_terminal(self) -> None:
        circuit = _circuit(
            "terminal-observation",
            1,
            _operation(OpCode.H, 0, "terminal-h"),
            _operation(OpCode.MEASURE, 0, "terminal-measure"),
            _operation(OpCode.X, 0, "terminal-x"),
        )

        with self.assertRaises(DensityMatrixTerminalObservationError) as captured:
            simulate_density_matrix(circuit)

        self.assertEqual(captured.exception.code, "A202")

    def test_readout_error_only_changes_reported_logical_distribution(self) -> None:
        result = run(
            _reported_one,
            execution=DensityMatrixExecutionRequest(
                ExecutableNoiseModel(
                    readout_channel=BinaryReadoutChannel(0.1, 0.25),
                )
            ),
        )

        self.assertIsInstance(result, DensityMatrixLogicalRunResult)
        assert isinstance(result, DensityMatrixLogicalRunResult)
        assert result.physical_classical_output_distribution is not None
        assert result.reported_classical_output_distribution is not None
        self.assertEqual(
            result.physical_classical_output_distribution.probabilities,
            (0.0, 1.0),
        )
        self.assertEqual(
            result.reported_classical_output_distribution.probabilities,
            (0.25, 0.75),
        )
        self.assertEqual(result.simulation.probabilities, (0.0, 1.0))

    def test_joint_readout_transform_is_independent_per_distinct_observation(self) -> None:
        result = run(
            _reported_zero_pair,
            execution=DensityMatrixExecutionRequest(
                ExecutableNoiseModel(
                    readout_channel=BinaryReadoutChannel(0.1, 0.25),
                )
            ),
        )

        self.assertIsInstance(result, DensityMatrixLogicalRunResult)
        assert isinstance(result, DensityMatrixLogicalRunResult)
        assert result.reported_classical_output_distribution is not None
        for actual, expected in zip(
            result.reported_classical_output_distribution.probabilities,
            (0.81, 0.09, 0.09, 0.01),
            strict=True,
        ):
            self.assertAlmostEqual(actual, expected)

    def test_readout_aliases_are_noisified_once_per_distinct_observation(self) -> None:
        result = run(
            _reported_alias,
            execution=DensityMatrixExecutionRequest(
                ExecutableNoiseModel(
                    readout_channel=BinaryReadoutChannel(0.5, 0.5),
                )
            ),
        )

        self.assertIsInstance(result, DensityMatrixLogicalRunResult)
        assert isinstance(result, DensityMatrixLogicalRunResult)
        assert result.reported_classical_output_distribution is not None
        self.assertEqual(
            result.reported_classical_output_distribution.probabilities,
            (0.5, 0.0, 0.0, 0.5),
        )

    def test_density_execution_rejects_amplitude_trace_capture_and_uses_sdk_run(self) -> None:
        from ariadion import DensityMatrixExecutionRequest as SdkDensityMatrixExecutionRequest

        result = run(_reported_one, execution=SdkDensityMatrixExecutionRequest())
        self.assertIsInstance(result, DensityMatrixLogicalRunResult)

        with self.assertRaises(DensityMatrixTraceUnsupportedError) as captured:
            run(
                _reported_one,
                execution=SdkDensityMatrixExecutionRequest(),
                trace=TraceCaptureOptions(enabled=True),
            )
        self.assertEqual(captured.exception.code, "A205")

        builder = _circuit("sdk-builder", 1, _operation(OpCode.H, 0, "sdk-builder-h"))
        builder_result = run(
            _builder_program(builder),
            execution=SdkDensityMatrixExecutionRequest(),
        )
        self.assertIsInstance(builder_result, DensityMatrixRunResult)

    def test_simulation_request_rejects_model_feature_mismatch(self) -> None:
        model = ExecutableNoiseModel(
            gate_channels=(GateChannelBinding(OneQubitGate.X, BitFlipChannel(0.2)),)
        )

        with self.assertRaisesRegex(ValueError, "must match"):
            SimulationRequest(
                EvolutionModel.DENSITY_MATRIX,
                NoiseModelOrigin.DECLARED,
                (NoiseFeature.READOUT_ERRORS,),
                noise_model=model,
            )

    def _assert_matrix_almost_equal(
        self,
        actual: tuple[tuple[complex, ...], ...],
        expected: tuple[tuple[complex, ...], ...],
    ) -> None:
        self.assertEqual(len(actual), len(expected))
        for row, expected_row in zip(actual, expected, strict=True):
            self.assertEqual(len(row), len(expected_row))
            for value, expected_value in zip(row, expected_row, strict=True):
                self.assertAlmostEqual(value.real, expected_value.real)
                self.assertAlmostEqual(value.imag, expected_value.imag)


def _builder_program(circuit: CircuitIR):
    from ariadion_language import Program

    program = Program(circuit.qubit_count, name=circuit.name)
    for operation in circuit.operations:
        if operation.opcode is OpCode.H:
            program.h(operation.targets[0])
        else:  # pragma: no cover - this helper currently builds one H operation
            raise AssertionError(f"unsupported builder test operation: {operation.opcode}")
    return program


if __name__ == "__main__":
    unittest.main()
