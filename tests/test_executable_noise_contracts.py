from __future__ import annotations

import json
import unittest
from math import sqrt

from ariadion_core import IrOperationId, ProgramId
from ariadion_ir import CircuitIR, OpCode, Operation
from ariadion_semantics import (
    AmplitudeDampingChannel,
    BinaryReadoutChannel,
    BitFlipChannel,
    DepolarizingChannel,
    EvolutionModel,
    ExecutableNoiseModel,
    GateChannelBinding,
    GateNoise,
    IdleNoise,
    NoiseBindingResult,
    NoiseFeature,
    NoiseModelOrigin,
    NoiseProfile,
    PhaseDampingChannel,
    PhaseFlipChannel,
    QuantumChannel,
    ReadoutChannelBinding,
    SimulationRequest,
)
from ariadion_simulator import SampledExecutionRequest, simulate


class ExecutableNoiseContractTests(unittest.TestCase):
    def test_public_sdk_reexports_noise_contracts_and_request_provenance(self) -> None:
        from ariadion import (
            AmplitudeDampingChannel as SdkAmplitudeDampingChannel,
            BinaryReadoutChannel as SdkBinaryReadoutChannel,
            BitFlipChannel as SdkBitFlipChannel,
            DepolarizingChannel as SdkDepolarizingChannel,
            EvolutionModel as SdkEvolutionModel,
            ExecutableNoiseModel as SdkExecutableNoiseModel,
            GateChannelBinding as SdkGateChannelBinding,
            NoiseBindingResult as SdkNoiseBindingResult,
            NoiseFeature as SdkNoiseFeature,
            NoiseModelOrigin as SdkNoiseModelOrigin,
            OpCode as SdkOpCode,
            PhaseDampingChannel as SdkPhaseDampingChannel,
            PhaseFlipChannel as SdkPhaseFlipChannel,
            QuantumChannel as SdkQuantumChannel,
            ReadoutChannelBinding as SdkReadoutChannelBinding,
            SimulationRequest as SdkSimulationRequest,
        )

        self.assertIs(SdkAmplitudeDampingChannel, AmplitudeDampingChannel)
        self.assertIs(SdkBinaryReadoutChannel, BinaryReadoutChannel)
        self.assertIs(SdkBitFlipChannel, BitFlipChannel)
        self.assertIs(SdkDepolarizingChannel, DepolarizingChannel)
        self.assertIs(SdkEvolutionModel, EvolutionModel)
        self.assertIs(SdkExecutableNoiseModel, ExecutableNoiseModel)
        self.assertIs(SdkGateChannelBinding, GateChannelBinding)
        self.assertIs(SdkNoiseBindingResult, NoiseBindingResult)
        self.assertIs(SdkNoiseFeature, NoiseFeature)
        self.assertIs(SdkNoiseModelOrigin, NoiseModelOrigin)
        self.assertIs(SdkOpCode, OpCode)
        self.assertIs(SdkPhaseDampingChannel, PhaseDampingChannel)
        self.assertIs(SdkPhaseFlipChannel, PhaseFlipChannel)
        self.assertIs(SdkQuantumChannel, QuantumChannel)
        self.assertIs(SdkReadoutChannelBinding, ReadoutChannelBinding)
        self.assertIs(SdkSimulationRequest, SimulationRequest)

    def test_typed_channels_validate_probabilities_and_serialize_deterministically(self) -> None:
        channels = (
            BitFlipChannel(0.1),
            PhaseFlipChannel(0.2),
            DepolarizingChannel(0.3),
            AmplitudeDampingChannel(0.4),
            PhaseDampingChannel(0.5),
        )

        self.assertEqual(
            [channel.to_dict() for channel in channels],
            [
                {"kind": "bit_flip", "probability": 0.1},
                {"kind": "phase_flip", "probability": 0.2},
                {"kind": "depolarizing", "probability": 0.3},
                {"kind": "amplitude_damping", "probability": 0.4},
                {"kind": "phase_damping", "probability": 0.5},
            ],
        )
        for channel in channels:
            with self.subTest(channel=channel.to_dict()["kind"]):
                self.assertEqual(channel.to_json(), channel.to_json())
                self.assertEqual(json.loads(channel.to_json()), channel.to_dict())
                self._assert_trace_preserving(channel.kraus_operators())

        for channel_type in (
            BitFlipChannel,
            PhaseFlipChannel,
            DepolarizingChannel,
            AmplitudeDampingChannel,
            PhaseDampingChannel,
        ):
            for invalid_probability in (-0.01, 1.01, float("nan"), True):
                with self.subTest(
                    channel_type=channel_type.__name__,
                    invalid_probability=invalid_probability,
                ):
                    with self.assertRaisesRegex(ValueError, "probability"):
                        channel_type(invalid_probability)

    def test_amplitude_and_phase_damping_have_validated_kraus_parameters(self) -> None:
        amplitude = AmplitudeDampingChannel(1.0)
        phase = PhaseDampingChannel(1.0)

        self.assertEqual(amplitude.kraus_operators()[0][1][1], 0j)
        self.assertEqual(amplitude.kraus_operators()[1][0][1], 1 + 0j)
        self.assertEqual(phase.kraus_operators()[0][1][1], 0j)
        self.assertEqual(phase.kraus_operators()[1][1][1], 1 + 0j)

        for channel_type in (AmplitudeDampingChannel, PhaseDampingChannel):
            with self.subTest(channel_type=channel_type.__name__):
                with self.assertRaisesRegex(ValueError, "probability"):
                    channel_type(-0.001)
                with self.assertRaisesRegex(ValueError, "probability"):
                    channel_type(1.001)

        partial_amplitude = AmplitudeDampingChannel(0.25).kraus_operators()
        partial_phase = PhaseDampingChannel(0.75).kraus_operators()
        self.assertAlmostEqual(partial_amplitude[0][1][1].real, sqrt(0.75))
        self.assertAlmostEqual(partial_amplitude[1][0][1].real, sqrt(0.25))
        self.assertAlmostEqual(partial_phase[0][1][1].real, 0.5)
        self.assertAlmostEqual(partial_phase[1][1][1].real, sqrt(0.75))

    def test_descriptive_noise_profile_is_independent_from_typed_channels(self) -> None:
        profile = NoiseProfile(
            gate_channels=(
                GateNoise(
                    operation="vendor_native_gate",
                    channel="provider_specific_channel",
                    error_probability=0.05,
                ),
            ),
            idle_noise=IdleNoise(t1_ns=20_000, t2_ns=30_000),
        )
        model = ExecutableNoiseModel(
            gate_channels=(GateChannelBinding(OpCode.H, BitFlipChannel(0.01)),),
        )

        self.assertEqual(
            profile.gate_channels[0].channel,
            "provider_specific_channel",
        )
        self.assertNotIn("provider_specific_channel", model.to_json())
        self.assertNotIn("idle_noise", model.to_dict())

    def test_idle_noise_remains_explicit_unsupported_binding_evidence(self) -> None:
        idle_noise = IdleNoise(t1_ns=20_000, t2_ns=30_000)
        result = NoiseBindingResult(
            model=ExecutableNoiseModel(),
            assumptions=("schedule duration is unavailable",),
            unsupported_features=(NoiseFeature.IDLE_DECOHERENCE,),
        )

        self.assertEqual(idle_noise.to_dict(), {"t1_ns": 20000.0, "t2_ns": 30000.0})
        self.assertEqual(result.to_dict()["unsupported_features"], ["idle_decoherence"])

    def test_binary_readout_channel_preserves_asymmetric_classical_error(self) -> None:
        channel = BinaryReadoutChannel(
            p_one_given_zero=0.125,
            p_zero_given_one=0.25,
        )

        self.assertEqual(channel.probability(observed_bit=1, actual_bit=0), 0.125)
        self.assertEqual(channel.probability(observed_bit=0, actual_bit=0), 0.875)
        self.assertEqual(channel.probability(observed_bit=0, actual_bit=1), 0.25)
        self.assertEqual(channel.probability(observed_bit=1, actual_bit=1), 0.75)
        self.assertEqual(
            channel.to_dict(),
            {
                "kind": "binary_readout",
                "p_one_given_zero": 0.125,
                "p_zero_given_one": 0.25,
            },
        )
        with self.assertRaisesRegex(ValueError, "p_one_given_zero"):
            BinaryReadoutChannel(-0.1, 0.1)
        with self.assertRaisesRegex(ValueError, "p_zero_given_one"):
            BinaryReadoutChannel(0.1, 1.1)
        with self.assertRaisesRegex(ValueError, "observed_bit"):
            channel.probability(observed_bit=True, actual_bit=0)

    def test_gate_channels_bind_to_typed_lowered_single_qubit_opcodes(self) -> None:
        binding = GateChannelBinding(OpCode.H, BitFlipChannel(0.02))

        self.assertEqual(
            binding.to_dict(),
            {
                "opcode": "H",
                "channel": {"kind": "bit_flip", "probability": 0.02},
            },
        )
        with self.assertRaisesRegex(ValueError, "OpCode"):
            GateChannelBinding("H", BitFlipChannel(0.02))  # type: ignore[arg-type]
        with self.assertRaisesRegex(ValueError, "multi-qubit"):
            GateChannelBinding(OpCode.CX, BitFlipChannel(0.02))
        with self.assertRaisesRegex(ValueError, "single-qubit"):
            GateChannelBinding(OpCode.MEASURE, BitFlipChannel(0.02))

    def test_executable_model_canonicalizes_bindings_and_keeps_readout_classical(self) -> None:
        model = ExecutableNoiseModel(
            gate_channels=(
                GateChannelBinding(OpCode.Z, PhaseFlipChannel(0.03)),
                GateChannelBinding(OpCode.H, BitFlipChannel(0.02)),
            ),
            readout_channels=(
                ReadoutChannelBinding(
                    OpCode.MEASURE,
                    BinaryReadoutChannel(0.1, 0.2),
                ),
            ),
        )

        self.assertEqual(
            tuple(binding.opcode for binding in model.gate_channels),
            (OpCode.H, OpCode.Z),
        )
        self.assertEqual(model.to_json(), model.to_json())
        self.assertEqual(json.loads(model.to_json()), model.to_dict())
        with self.assertRaisesRegex(ValueError, "MEASURE opcode"):
            ReadoutChannelBinding(OpCode.H, BinaryReadoutChannel(0.1, 0.2))
        with self.assertRaisesRegex(ValueError, "must be unique"):
            ExecutableNoiseModel(
                gate_channels=(
                    GateChannelBinding(OpCode.H, BitFlipChannel(0.01)),
                    GateChannelBinding(OpCode.H, PhaseFlipChannel(0.01)),
                ),
            )

    def test_noise_binding_result_keeps_unsupported_features_visible(self) -> None:
        model = ExecutableNoiseModel(
            gate_channels=(GateChannelBinding(OpCode.X, BitFlipChannel(0.01)),),
        )
        result = NoiseBindingResult(
            model=model,
            assumptions=("manual typed channel translation",),
            unsupported_features=(
                NoiseFeature.CORRELATIONS,
                NoiseFeature.IDLE_DECOHERENCE,
                NoiseFeature.LEAKAGE,
            ),
        )

        self.assertEqual(
            result.to_dict()["unsupported_features"],
            ["idle_decoherence", "leakage", "correlations"],
        )
        self.assertEqual(json.loads(result.to_json()), result.to_dict())
        with self.assertRaisesRegex(ValueError, "must be unique"):
            NoiseBindingResult(
                model=model,
                unsupported_features=(NoiseFeature.LEAKAGE, NoiseFeature.LEAKAGE),
            )

    def test_simulation_request_requires_consistent_noise_provenance(self) -> None:
        model = ExecutableNoiseModel(
            gate_channels=(GateChannelBinding(OpCode.X, BitFlipChannel(0.01)),),
        )

        ideal = SimulationRequest(EvolutionModel.STATE_VECTOR, NoiseModelOrigin.NONE)
        self.assertIsNone(ideal.noise_model)
        with self.assertRaisesRegex(ValueError, "NONE cannot carry a noise model"):
            SimulationRequest(
                EvolutionModel.STATE_VECTOR,
                NoiseModelOrigin.NONE,
                noise_model=model,
            )
        with self.assertRaisesRegex(ValueError, "NONE cannot carry a noise model"):
            SimulationRequest(
                EvolutionModel.STATE_VECTOR,
                NoiseModelOrigin.NONE,
                noise_model_reference="declared:lab-model-v1",
            )
        with self.assertRaisesRegex(ValueError, "DECLARED requires"):
            SimulationRequest(EvolutionModel.DENSITY_MATRIX, NoiseModelOrigin.DECLARED)

        declared = SimulationRequest(
            EvolutionModel.DENSITY_MATRIX,
            NoiseModelOrigin.DECLARED,
            (NoiseFeature.GATE_CHANNELS,),
            noise_model=model,
        )
        self.assertEqual(declared.noise_model, model)
        declared_reference = SimulationRequest(
            EvolutionModel.DENSITY_MATRIX,
            NoiseModelOrigin.DECLARED,
            noise_model_reference="declared:lab-model-v1",
        )
        self.assertEqual(
            declared_reference.noise_model_reference,
            "declared:lab-model-v1",
        )
        device_profile = SimulationRequest(
            EvolutionModel.DENSITY_MATRIX,
            NoiseModelOrigin.DEVICE_PROFILE,
            noise_model_reference="device-profile:future-calibration",
        )
        self.assertEqual(
            device_profile.noise_model_reference,
            "device-profile:future-calibration",
        )
        with self.assertRaisesRegex(ValueError, "DEVICE_PROFILE requires"):
            SimulationRequest(EvolutionModel.DENSITY_MATRIX, NoiseModelOrigin.DEVICE_PROFILE)

    def test_current_exact_and_sampled_statevector_execution_remain_ideal(self) -> None:
        circuit = CircuitIR(
            ProgramId("noise-contract:ideal-execution"),
            "noise-contract-ideal-execution",
            1,
            (
                Operation(OpCode.X, (0,), IrOperationId("noise-contract:x")),
                Operation(
                    OpCode.MEASURE,
                    (0,),
                    IrOperationId("noise-contract:measure"),
                ),
            ),
        )

        exact = simulate(circuit)
        sampled = simulate(circuit, execution=SampledExecutionRequest(shots=3, seed=9))

        self.assertEqual(exact.amplitudes, (0j, 1 + 0j))
        self.assertEqual(
            tuple(shot.measurement_outcomes[0].outcome for shot in sampled.shots),
            ((1,), (1,), (1,)),
        )

    def _assert_trace_preserving(
        self,
        operators: tuple[tuple[tuple[complex, complex], tuple[complex, complex]], ...],
    ) -> None:
        total = [[0j, 0j], [0j, 0j]]
        for operator in operators:
            for row in range(2):
                for column in range(2):
                    total[row][column] += sum(
                        operator[index][row].conjugate() * operator[index][column]
                        for index in range(2)
                    )
        for row in range(2):
            for column in range(2):
                expected = 1 if row == column else 0
                self.assertAlmostEqual(total[row][column].real, expected)
                self.assertAlmostEqual(total[row][column].imag, 0)


if __name__ == "__main__":
    unittest.main()
