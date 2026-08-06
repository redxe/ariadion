from __future__ import annotations

import json
import unittest
from dataclasses import FrozenInstanceError

from ariadion_semantics import (
    CorrelationModel,
    GateNoise,
    IdleNoise,
    LeakageModel,
    NoiseProfile,
    ProtectionPlan,
    ProtectionStrategy,
    ReadoutNoise,
    ReliabilityGoal,
    SimulationFidelity,
)


class ReliabilityContractTests(unittest.TestCase):
    def test_reliability_goal_is_immutable_and_serializes_deterministically(self) -> None:
        goal = ReliabilityGoal(0.000001, confidence=0.95)

        self.assertEqual(
            goal.to_dict(),
            {"maximum_failure_probability": 0.000001, "confidence": 0.95},
        )
        self.assertEqual(
            goal.to_json(),
            '{"confidence":0.95,"maximum_failure_probability":1e-06}',
        )
        with self.assertRaises(FrozenInstanceError):
            goal.confidence = 0.9  # type: ignore[misc]

    def test_noise_profile_preserves_distinct_noise_assumptions(self) -> None:
        profile = NoiseProfile(
            gate_channels=(
                GateNoise(
                    operation="cx",
                    channel="depolarizing",
                    error_probability=0.001,
                    duration_ns=50,
                ),
            ),
            idle_noise=IdleNoise(t1_ns=30_000, t2_ns=40_000),
            readout_noise=ReadoutNoise(0.02),
            leakage=LeakageModel(0.0001),
            correlations=CorrelationModel("rare_correlated_event", 0.00001),
        )

        self.assertEqual(
            profile.to_dict(),
            {
                "gate_channels": [
                    {
                        "operation": "cx",
                        "channel": "depolarizing",
                        "error_probability": 0.001,
                        "duration_ns": 50.0,
                    },
                ],
                "idle_noise": {"t1_ns": 30000.0, "t2_ns": 40000.0},
                "readout_noise": {"error_probability": 0.02},
                "leakage": {"leakage_probability": 0.0001},
                "correlations": {
                    "name": "rare_correlated_event",
                    "event_probability": 0.00001,
                },
            },
        )
        self.assertEqual(json.loads(profile.to_json()), profile.to_dict())
        self.assertIsInstance(profile.leakage, LeakageModel)
        self.assertIsInstance(profile.correlations, CorrelationModel)
        with self.assertRaises(FrozenInstanceError):
            profile.idle_noise = None  # type: ignore[misc]

    def test_noise_contracts_reject_invalid_probability_and_time_values(self) -> None:
        with self.assertRaisesRegex(ValueError, "maximum failure probability"):
            ReliabilityGoal(0)
        with self.assertRaisesRegex(ValueError, "reliability confidence"):
            ReliabilityGoal(0.1, confidence=1.1)
        with self.assertRaisesRegex(ValueError, "gate noise error probability"):
            GateNoise("h", "depolarizing", -0.01)
        with self.assertRaisesRegex(ValueError, "gate noise duration_ns"):
            GateNoise("h", "depolarizing", 0.01, duration_ns=-1)
        with self.assertRaisesRegex(ValueError, "requires t1_ns or t2_ns"):
            IdleNoise()
        with self.assertRaisesRegex(ValueError, "t2_ns"):
            IdleNoise(t1_ns=10, t2_ns=21)
        with self.assertRaisesRegex(ValueError, "readout error probability"):
            ReadoutNoise(float("nan"))
        with self.assertRaisesRegex(ValueError, "leakage probability"):
            LeakageModel(1.1)
        with self.assertRaisesRegex(ValueError, "correlation event probability"):
            CorrelationModel("crosstalk", -0.01)
        with self.assertRaisesRegex(ValueError, "gate_channels"):
            NoiseProfile(
                gate_channels=[GateNoise("h", "depolarizing", 0.01)]  # type: ignore[arg-type]
            )

    def test_protection_plan_preserves_planner_output_without_selecting_it(self) -> None:
        plan = ProtectionPlan(
            ProtectionStrategy.FAULT_TOLERANT,
            code_name="surface_code",
            code_distance=7,
            estimated_failure_probability=0.000001,
            physical_qubit_count=101,
            assumptions=("below_threshold", "decoder_model_v1"),
        )

        self.assertEqual(
            plan.strategy, ProtectionStrategy.FAULT_TOLERANT)
        self.assertEqual(
            plan.to_dict()["assumptions"], ["below_threshold", "decoder_model_v1"])
        self.assertEqual(json.loads(plan.to_json()), plan.to_dict())
        with self.assertRaisesRegex(ValueError, "code_distance"):
            ProtectionPlan(
                ProtectionStrategy.BARE,
                code_name=None,
                code_distance=0,
                estimated_failure_probability=0.1,
                physical_qubit_count=1,
                assumptions=(),
            )
        with self.assertRaisesRegex(ValueError, "physical_qubit_count"):
            ProtectionPlan(
                ProtectionStrategy.BARE,
                code_name=None,
                code_distance=None,
                estimated_failure_probability=0.1,
                physical_qubit_count=-1,
                assumptions=(),
            )

    def test_fidelity_and_protection_enums_expose_the_documented_values(self) -> None:
        self.assertEqual(
            [fidelity.value for fidelity in SimulationFidelity],
            [
                "ideal",
                "stochastic",
                "decoherence",
                "device_profile",
                "correlated",
                "protected",
            ],
        )
        self.assertEqual(
            [strategy.value for strategy in ProtectionStrategy],
            ["bare", "mitigated", "error_detected", "fault_tolerant"],
        )


if __name__ == "__main__":
    unittest.main()
