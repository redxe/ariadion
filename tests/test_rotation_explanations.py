from __future__ import annotations

import math
import unittest

from ariadion import (
    Program,
    RotationAxis,
    RotationEffect,
    TraceCaptureOptions,
    deg,
    inspect_execution_trace,
    rad,
    run,
)


class RotationExplanationTests(unittest.TestCase):
    def test_ry_explanation_reports_probability_redistribution(self) -> None:
        inspection = self._inspect(Program(1).ry(0, deg(90)))
        step = inspection.steps[0]
        explanation = step.rotation_explanation

        self.assertIsNotNone(explanation)
        assert explanation is not None
        self.assertEqual(explanation.axis, RotationAxis.Y)
        self.assertEqual(explanation.target, 0)
        self.assertAlmostEqual(explanation.angle_radians, math.pi / 2)
        self.assertIsNotNone(explanation.source_angle)
        assert explanation.source_angle is not None
        self.assertEqual(explanation.source_angle.source_value, 90.0)
        self.assertEqual(explanation.source_angle.source_unit, "degrees")
        self.assertTrue(explanation.probabilities_changed)
        self.assertFalse(explanation.relative_phase_changed)
        self.assertEqual(explanation.effect, RotationEffect.PROBABILITIES_CHANGED)
        self.assertTrue(
            any("probabilities changed" in claim for claim in explanation.exact_claims)
        )
        self.assertIn("Bloch-sphere", explanation.educational_interpretation)

        probabilities = {
            state.label: state.probability for state in step.transition.after.states
        }
        self.assertAlmostEqual(probabilities["|0>"], 0.5)
        self.assertAlmostEqual(probabilities["|1>"], 0.5)

    def test_rz_explanation_reports_relative_phase_without_probability_change(self) -> None:
        inspection = self._inspect(
            Program(1).ry(0, rad(math.pi / 3)).rz(0, deg(180))
        )
        step = inspection.steps[1]
        explanation = step.rotation_explanation

        self.assertIsNotNone(explanation)
        assert explanation is not None
        self.assertEqual(explanation.axis, RotationAxis.Z)
        self.assertFalse(explanation.probabilities_changed)
        self.assertTrue(explanation.relative_phase_changed)
        self.assertEqual(explanation.effect, RotationEffect.RELATIVE_PHASE_ONLY)
        self.assertTrue(
            any(
                "preserves computational-basis probabilities" in claim
                for claim in explanation.exact_claims
            )
        )
        self.assertIn("interference", explanation.educational_interpretation)

        change = step.transition.basis_state_changes[0]
        self.assertEqual(change.label, "|1>")
        self.assertAlmostEqual(change.probability_delta, 0.0)
        self.assertIsNotNone(change.phase_change_radians)
        assert change.phase_change_radians is not None
        self.assertAlmostEqual(abs(change.phase_change_radians), math.pi)

    def test_global_only_phase_is_exactly_labeled_unobservable(self) -> None:
        inspection = self._inspect(Program(1).rz(0, rad(math.pi / 2)))
        explanation = inspection.steps[0].rotation_explanation

        self.assertIsNotNone(explanation)
        assert explanation is not None
        self.assertFalse(explanation.probabilities_changed)
        self.assertFalse(explanation.relative_phase_changed)
        self.assertEqual(explanation.effect, RotationEffect.GLOBAL_PHASE_ONLY)
        self.assertIsNotNone(explanation.global_phase_delta_radians)
        assert explanation.global_phase_delta_radians is not None
        self.assertAlmostEqual(
            abs(explanation.global_phase_delta_radians),
            math.pi / 4,
        )
        self.assertTrue(
            any(
                "global phase" in claim and "unobservable" in claim
                for claim in explanation.exact_claims
            )
        )
        self.assertFalse(
            any("A relative phase changed" in claim for claim in explanation.exact_claims)
        )

    def test_non_rotation_steps_have_no_rotation_explanation(self) -> None:
        inspection = self._inspect(Program(1).h(0))

        self.assertIsNone(inspection.steps[0].rotation_explanation)

    def _inspect(self, program: Program):
        result = run(program, trace=TraceCaptureOptions(enabled=True))
        self.assertIsNotNone(result.trace)
        assert result.trace is not None
        return inspect_execution_trace(result.trace)


if __name__ == "__main__":
    unittest.main()
