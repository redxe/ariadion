from __future__ import annotations

import math
import unittest

from ariadion import Program, run
from daidalon import CompileError, compile_program


class VerticalSliceTests(unittest.TestCase):
    def test_bell_state(self) -> None:
        result = run(Program(2, name="bell").h(0).cx(0, 1))

        self.assertAlmostEqual(result.simulation.probabilities[0], 0.5)
        self.assertAlmostEqual(result.simulation.probabilities[3], 0.5)
        self.assertEqual(result.inspection.entangled_qubits, (0, 1))
        self.assertIn("q0:", result.circuit)
        self.assertIn("entanglement hint", result.report)

    def test_phase_is_visible(self) -> None:
        result = run(Program(1, name="phase").h(0).z(0))
        states = result.inspection.states

        self.assertEqual(len(states), 2)
        self.assertAlmostEqual(states[0].phase_radians, 0.0)
        self.assertAlmostEqual(abs(states[1].phase_radians), math.pi)

    def test_compiler_collects_diagnostics(self) -> None:
        program = Program(2).cx(0, 0).x(4)
        with self.assertRaises(CompileError) as captured:
            compile_program(program)

        codes = {diagnostic.code for diagnostic in captured.exception.diagnostics}
        self.assertEqual(codes, {"A102", "A103"})


if __name__ == "__main__":
    unittest.main()
