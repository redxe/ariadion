from __future__ import annotations

import json
import unittest

from ariadion import (
    Program,
    ProgramId,
    SourceNodeId,
    TraceCaptureOptions,
    TraceDebuggerError,
    TraceDebuggerSession,
    inspect_execution_trace,
    run,
)
from ariadion_ir import OpCode
from ariadion_visualization import render_circuit
from ariadion_cli.trace_view import render_trace_step


class TraceDebuggerTests(unittest.TestCase):
    def _bell_session(self) -> TraceDebuggerSession:
        program = Program(2, name="bell", program_id=ProgramId("examples/debugger.py"))
        program.h(0, source_node_id=SourceNodeId("node:debugger:h"))
        program.cx(0, 1, source_node_id=SourceNodeId("node:debugger:cx"))
        result = run(program, trace=TraceCaptureOptions(enabled=True))

        self.assertIsNotNone(result.trace)
        assert result.trace is not None
        return TraceDebuggerSession(
            result.ir,
            result.trace,
            inspect_execution_trace(result.trace),
        )

    def test_session_exposes_frontend_neutral_active_step_data(self) -> None:
        session = self._bell_session()

        view = session.current_view
        self.assertEqual(view.step_index, 0)
        self.assertEqual(view.step_number, 1)
        self.assertEqual(view.step_count, 2)
        self.assertEqual(view.operation.opcode, OpCode.H)
        self.assertEqual(view.ir_operation_id, view.operation.id)
        self.assertIsNotNone(view.source)
        assert view.source is not None
        self.assertEqual(view.source.source_node_id, "node:debugger:h")
        self.assertEqual(view.basis_state_changes[0].label, "|00>")

        payload = json.loads(view.to_json())
        self.assertEqual(payload["step_number"], 1)
        self.assertEqual(payload["operation"]["opcode"], "H")
        self.assertEqual(payload["operation"]["source"]["source_node_id"], "node:debugger:h")

    def test_session_navigation_is_immutable_and_bounded(self) -> None:
        session = self._bell_session()

        next_session = session.next()
        self.assertEqual(session.current_step_index, 0)
        self.assertEqual(next_session.current_step_index, 1)
        self.assertEqual(next_session.current_view.operation.opcode, OpCode.CX)
        self.assertEqual(next_session.next(), next_session)
        self.assertEqual(next_session.previous().current_step_index, 0)
        self.assertEqual(session.go_to(1), next_session)
        with self.assertRaises(TraceDebuggerError):
            session.go_to(2)

    def test_active_circuit_render_marks_the_selected_operation(self) -> None:
        session = self._bell_session()

        rendered = render_circuit(
            session.circuit,
            active_operation_index=session.next().current_step_index,
        )

        self.assertIn("─[H]─", rendered)
        self.assertIn("══●══", rendered)
        self.assertIn("═[X]═", rendered)

    def test_renderer_marks_global_phase_as_unobservable_and_shows_measurements(self) -> None:
        program = Program(1, name="measurement")
        program.x(0).z(0).measure(0, key="result")
        result = run(program, trace=TraceCaptureOptions(enabled=True))

        self.assertIsNotNone(result.trace)
        assert result.trace is not None
        session = TraceDebuggerSession(
            result.ir,
            result.trace,
            inspect_execution_trace(result.trace),
        )

        global_phase = render_trace_step(session.view_at(1))
        measurement = render_trace_step(session.view_at(2))
        self.assertIn("Global phase: +3.141593 rad (unobservable)", global_phase)
        self.assertIn("Exact measurement probabilities (q0, key='result'):", measurement)
        self.assertIn("|1> p=1.000000", measurement)


if __name__ == "__main__":
    unittest.main()
