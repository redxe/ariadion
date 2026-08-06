from __future__ import annotations

import json
import math
import unittest

from ariadion import (
    Program,
    ProgramId,
    SourceNodeId,
    TraceCaptureOptions,
    inspect_execution_trace,
    run,
)
from ariadion_ir import OpCode
from ariadion_runtime import ExecutionMode
from theonoe import inspect_amplitudes


class TraceInspectionTests(unittest.TestCase):
    def test_bell_trace_inspection_exposes_state_and_entanglement_changes(self) -> None:
        program = Program(2, name="bell", program_id=ProgramId("examples/bell-inspection.py"))
        program.h(0, source_node_id=SourceNodeId("node:bell:h"))
        program.cx(0, 1, source_node_id=SourceNodeId("node:bell:cx"))

        result = run(program, trace=TraceCaptureOptions(enabled=True))
        inspection = result.trace_inspection

        self.assertIsNotNone(inspection)
        assert inspection is not None
        self.assertEqual(inspection.circuit_id, result.ir.id)
        self.assertEqual(inspection.initial.states[0].label, "|00>")
        self.assertEqual(inspection.initial.states[0].probability, 1.0)
        self.assertEqual(inspection.initial.entangled_qubits, ())
        self.assertEqual(inspection.final, result.inspection)

        h_step, cx_step = inspection.steps
        self.assertEqual(h_step.index, 0)
        self.assertEqual(h_step.ir_operation_id, result.ir.operations[0].id)
        self.assertEqual(h_step.source, result.ir.operations[0].source)
        self.assertEqual(h_step.opcode, OpCode.H)
        self.assertEqual(h_step.transition.before.states[0].label, "|00>")
        self.assertEqual(
            tuple(change.label for change in h_step.transition.basis_state_changes),
            ("|00>", "|01>"),
        )
        self.assertEqual(h_step.transition.after.entangled_qubits, ())
        self.assertEqual(h_step.transition.entanglement.newly_entangled, ())
        self.assertEqual(h_step.transition.entanglement.persistent_separable, (0, 1))
        self.assertIsNotNone(h_step.transition.after.separability)
        assert h_step.transition.after.separability is not None
        self.assertTrue(h_step.transition.after.separability.proven_fully_separable)
        self.assertEqual(
            h_step.transition.after.separability.heuristic_subsystems,
            ((0,), (1,)),
        )
        for reduced in h_step.transition.after.reduced_density_matrices:
            self.assertAlmostEqual(reduced.purity, 1.0)
            self.assertTrue(reduced.is_separable_from_rest)

        self.assertEqual(cx_step.index, 1)
        self.assertEqual(cx_step.ir_operation_id, result.ir.operations[1].id)
        self.assertEqual(cx_step.source, result.ir.operations[1].source)
        self.assertIsNotNone(cx_step.source)
        assert cx_step.source is not None
        self.assertEqual(cx_step.source.source_node_id, "node:bell:cx")
        self.assertEqual(cx_step.opcode, OpCode.CX)
        self.assertEqual(cx_step.transition.before, h_step.transition.after)
        self.assertEqual(cx_step.transition.after.entangled_qubits, (0, 1))
        self.assertEqual(cx_step.transition.entanglement.newly_entangled, (0, 1))
        self.assertEqual(cx_step.transition.entanglement.persistent_separable, ())
        self.assertIsNotNone(cx_step.transition.after.separability)
        assert cx_step.transition.after.separability is not None
        self.assertFalse(cx_step.transition.after.separability.proven_fully_separable)
        self.assertEqual(cx_step.transition.after.separability.heuristic_subsystems, ((0, 1),))
        for reduced in cx_step.transition.after.reduced_density_matrices:
            self.assertAlmostEqual(reduced.rho_00.real, 0.5)
            self.assertAlmostEqual(reduced.rho_11.real, 0.5)
            self.assertEqual(reduced.rho_01, 0j)
            self.assertEqual(reduced.rho_10, 0j)
            self.assertAlmostEqual(reduced.purity, 0.5)
            self.assertFalse(reduced.is_separable_from_rest)

    def test_transition_reports_phase_changes_without_probability_changes(self) -> None:
        program = Program(1, program_id=ProgramId("examples/phase-inspection.py"))
        program.h(0).z(0)

        inspection = run(program, trace=TraceCaptureOptions(enabled=True)).trace_inspection

        self.assertIsNotNone(inspection)
        assert inspection is not None
        z_transition = inspection.steps[1].transition
        self.assertEqual(
            tuple(change.label for change in z_transition.basis_state_changes),
            ("|1>",),
        )
        change = z_transition.basis_state_changes[0]
        self.assertAlmostEqual(change.before_probability, 0.5)
        self.assertAlmostEqual(change.after_probability, 0.5)
        self.assertAlmostEqual(change.probability_delta, 0.0)
        self.assertIsNotNone(change.phase_change_radians)
        assert change.phase_change_radians is not None
        self.assertAlmostEqual(abs(change.phase_change_radians), math.pi)

    def test_measurement_transition_retains_state_and_reports_exact_data(self) -> None:
        program = Program(1, program_id=ProgramId("examples/measurement-inspection.py"))
        program.h(0).measure(0, key="result")

        inspection = run(program, trace=TraceCaptureOptions(enabled=True)).trace_inspection

        self.assertIsNotNone(inspection)
        assert inspection is not None
        measurement_step = inspection.steps[-1]
        self.assertEqual(measurement_step.opcode, OpCode.MEASURE)
        self.assertEqual(measurement_step.transition.basis_state_changes, ())
        self.assertEqual(measurement_step.transition.before, measurement_step.transition.after)
        self.assertIsNotNone(measurement_step.measurement)
        assert measurement_step.measurement is not None
        self.assertAlmostEqual(measurement_step.measurement.probabilities[0], 0.5)
        self.assertAlmostEqual(measurement_step.measurement.probabilities[1], 0.5)

    def test_amplitude_inspection_distinguishes_proof_from_heuristic_grouping(self) -> None:
        scale = 1 / math.sqrt(2)
        product_report = inspect_amplitudes((scale + 0j, scale + 0j, 0j, 0j), 2)
        paired_bell_amplitudes = tuple(
            0.5 + 0j if index in {0, 3, 12, 15} else 0j
            for index in range(16)
        )
        paired_bell_report = inspect_amplitudes(
            paired_bell_amplitudes,
            4,
        )

        self.assertIsNotNone(product_report.separability)
        assert product_report.separability is not None
        self.assertTrue(product_report.separability.proven_fully_separable)
        self.assertEqual(product_report.separability.heuristic_subsystems, ((0,), (1,)))

        self.assertIsNotNone(paired_bell_report.separability)
        assert paired_bell_report.separability is not None
        self.assertFalse(paired_bell_report.separability.proven_fully_separable)
        self.assertEqual(paired_bell_report.entangled_qubits, (0, 1, 2, 3))
        self.assertEqual(
            paired_bell_report.separability.heuristic_subsystems,
            ((0, 1, 2, 3),),
        )

    def test_trace_inspection_is_versioned_structured_data(self) -> None:
        result = run(Program(1).h(0), trace=TraceCaptureOptions(enabled=True))
        inspection = result.trace_inspection

        self.assertIsNotNone(inspection)
        assert inspection is not None
        self.assertIsNotNone(result.trace)
        assert result.trace is not None
        self.assertEqual(inspect_execution_trace(result.trace), inspection)
        payload = json.loads(inspection.to_json())
        self.assertEqual(payload["circuit_id"], result.ir.id)
        self.assertEqual(payload["trace_schema_version"], result.trace.schema_version)
        self.assertEqual(payload["steps"][0]["operation"]["opcode"], "H")
        self.assertEqual(payload["steps"][0]["transition"]["after"]["states"][0]["label"], "|0>")
        self.assertEqual(result.trace.metadata.mode, ExecutionMode.EXACT)


if __name__ == "__main__":
    unittest.main()
