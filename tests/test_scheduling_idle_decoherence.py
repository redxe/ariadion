"""Tests for deterministic ASAP scheduling and T1/T2 idle decoherence.

Covers:
- deterministic schedule
- overlapping disjoint gates
- timing serialization
- missing-duration error
- idle interval calculation
- zero-duration idle channel computation (identity evolution)
- T1 amplitude damping
- T2 pure phase damping
- combined T1/T2 coherence decay
- invalid T2 > 2*T1
- |1> relaxation
- coherence loss without population change
- Bell-state degradation
- reference/NumPy parity
- existing unscheduled behavior unchanged
- full PSD validation still catches unphysical matrix
- performance backend avoids unconditional cubic PSD audit
"""

from __future__ import annotations

import json
import unittest
from math import exp, isclose, pi, sqrt
from unittest.mock import patch

from ariadion_core import IrOperationId, ProgramId
from ariadion_ir import CircuitIR, OpCode, Operation
from ariadion_noise import IdleDecoherenceProfile, NoiseFeature
from ariadion_simulator import (
    DENSITY_MATRIX_POSITIVITY_ABS_TOLERANCE,
    DensityMatrixExecutionRequest,
    DensityMatrixInvariantError,
    DensityMatrixResult,
    ExecutionSchedule,
    IdleDecoherenceEvent,
    IdleInterval,
    MissingOperationTimingError,
    OperationTiming,
    OperationTimingError,
    ScheduledOperation,
    SchedulingInvariantError,
    SimulationCapabilities,
    SimulationQuery,
    StateRepresentation,
    idle_decoherence_channels_for_duration,
    schedule_asap,
    simulate_density_matrix,
    validate_density_matrix,
)
from ariadion_simulator_numpy import NumpyDensityMatrixBackend


def _op(
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
        IrOperationId(f"sched:{name}"),
        controls=() if control is None else (control,),
        angle_radians=angle_radians,
    )


def _circuit(name: str, width: int, *operations: Operation) -> CircuitIR:
    return CircuitIR(ProgramId(f"sched:{name}"), name, width, tuple(operations))


# ---------------------------------------------------------------------------
# Scheduling contracts
# ---------------------------------------------------------------------------

class SchedulingContractTests(unittest.TestCase):
    def test_operation_timing_rejects_zero_and_negative_and_non_finite(self) -> None:
        with self.assertRaisesRegex(OperationTimingError, "positive finite"):
            OperationTiming(IrOperationId("op1"), 0.0)
        with self.assertRaisesRegex(OperationTimingError, "positive finite"):
            OperationTiming(IrOperationId("op1"), -1.0)
        with self.assertRaisesRegex(OperationTimingError, "positive finite"):
            OperationTiming(IrOperationId("op1"), float("inf"))
        with self.assertRaisesRegex(OperationTimingError, "positive finite"):
            OperationTiming(IrOperationId("op1"), float("nan"))

    def test_operation_timing_equality_and_dict(self) -> None:
        t = OperationTiming(IrOperationId("op1"), 50.0)
        self.assertEqual(t.operation_id, "op1")
        self.assertEqual(t.duration_ns, 50.0)
        self.assertEqual(t, OperationTiming(IrOperationId("op1"), 50.0))
        self.assertNotEqual(t, OperationTiming(IrOperationId("op2"), 50.0))
        d = t.to_dict()
        self.assertEqual(d["operation_id"], "op1")
        self.assertEqual(d["duration_ns"], 50.0)
        self.assertEqual(json.loads(t.to_json()), d)

    def test_scheduled_operation_requires_end_greater_than_start(self) -> None:
        with self.assertRaisesRegex(SchedulingInvariantError, "greater than start_ns"):
            ScheduledOperation(IrOperationId("op1"), start_ns=10.0, end_ns=10.0)
        with self.assertRaisesRegex(SchedulingInvariantError, "greater than start_ns"):
            ScheduledOperation(IrOperationId("op1"), start_ns=10.0, end_ns=5.0)

    def test_scheduled_operation_duration_property(self) -> None:
        op = ScheduledOperation(IrOperationId("op1"), start_ns=10.0, end_ns=60.0)
        self.assertAlmostEqual(op.duration_ns, 50.0)

    def test_idle_interval_requires_positive_gap(self) -> None:
        with self.assertRaisesRegex(SchedulingInvariantError, "greater than start_ns"):
            IdleInterval(slot=0, start_ns=5.0, end_ns=5.0)
        with self.assertRaisesRegex(SchedulingInvariantError, "greater than start_ns"):
            IdleInterval(slot=0, start_ns=5.0, end_ns=3.0)

    def test_idle_interval_slot_must_be_non_negative_integer(self) -> None:
        with self.assertRaisesRegex(SchedulingInvariantError, "non-negative integer"):
            IdleInterval(slot=-1, start_ns=0.0, end_ns=1.0)

    def test_idle_interval_duration_property(self) -> None:
        ii = IdleInterval(slot=0, start_ns=10.0, end_ns=60.0)
        self.assertAlmostEqual(ii.duration_ns, 50.0)

    def test_execution_schedule_rejects_wrong_types(self) -> None:
        with self.assertRaisesRegex(SchedulingInvariantError, "tuple"):
            ExecutionSchedule(
                scheduled_operations=[],  # type: ignore[arg-type]
                idle_intervals=(),
                peak_duration_ns=0.0,
            )
        with self.assertRaisesRegex(SchedulingInvariantError, "non-negative"):
            ExecutionSchedule(
                scheduled_operations=(),
                idle_intervals=(),
                peak_duration_ns=-1.0,
            )

    def test_schedule_asap_single_qubit_sequential(self) -> None:
        h = _op(OpCode.H, 0, "h")
        x = _op(OpCode.X, 0, "x")
        circuit = _circuit("seq", 1, h, x)
        profile = {IrOperationId("sched:h"): 20.0, IrOperationId("sched:x"): 10.0}
        schedule = schedule_asap(circuit, profile)

        self.assertEqual(len(schedule.scheduled_operations), 2)
        op_h = schedule.timing_for_operation(IrOperationId("sched:h"))
        op_x = schedule.timing_for_operation(IrOperationId("sched:x"))
        self.assertIsNotNone(op_h)
        self.assertIsNotNone(op_x)
        assert op_h is not None and op_x is not None
        self.assertAlmostEqual(op_h.start_ns, 0.0)
        self.assertAlmostEqual(op_h.end_ns, 20.0)
        self.assertAlmostEqual(op_x.start_ns, 20.0)
        self.assertAlmostEqual(op_x.end_ns, 30.0)
        self.assertAlmostEqual(schedule.peak_duration_ns, 30.0)

    def test_schedule_asap_disjoint_operations_overlap(self) -> None:
        # Two independent single-qubit gates on separate qubits: both start at 0.
        h0 = _op(OpCode.H, 0, "h0")
        h1 = _op(OpCode.H, 1, "h1")
        circuit = _circuit("parallel", 2, h0, h1)
        profile = {
            IrOperationId("sched:h0"): 20.0,
            IrOperationId("sched:h1"): 30.0,
        }
        schedule = schedule_asap(circuit, profile)

        op_h0 = schedule.timing_for_operation(IrOperationId("sched:h0"))
        op_h1 = schedule.timing_for_operation(IrOperationId("sched:h1"))
        assert op_h0 is not None and op_h1 is not None
        # Both can start at 0 because they act on disjoint slots.
        self.assertAlmostEqual(op_h0.start_ns, 0.0)
        self.assertAlmostEqual(op_h1.start_ns, 0.0)
        self.assertAlmostEqual(schedule.peak_duration_ns, 30.0)

    def test_schedule_asap_cx_waits_for_both_slots(self) -> None:
        # H on q0 takes 20 ns; then CX(q0->q1) must wait until q0 is free.
        h0 = _op(OpCode.H, 0, "h0")
        cx = _op(OpCode.CX, 1, "cx", control=0)
        circuit = _circuit("cx-wait", 2, h0, cx)
        profile = {
            IrOperationId("sched:h0"): 20.0,
            IrOperationId("sched:cx"): 50.0,
        }
        schedule = schedule_asap(circuit, profile)

        op_cx = schedule.timing_for_operation(IrOperationId("sched:cx"))
        assert op_cx is not None
        self.assertAlmostEqual(op_cx.start_ns, 20.0)
        self.assertAlmostEqual(op_cx.end_ns, 70.0)

    def test_schedule_asap_deterministic_for_same_input(self) -> None:
        h = _op(OpCode.H, 0, "h")
        x = _op(OpCode.X, 0, "x")
        circuit = _circuit("det", 1, h, x)
        profile = {IrOperationId("sched:h"): 20.0, IrOperationId("sched:x"): 10.0}
        s1 = schedule_asap(circuit, profile)
        s2 = schedule_asap(circuit, profile)
        self.assertEqual(s1, s2)

    def test_missing_duration_raises_missing_operation_timing_error(self) -> None:
        h = _op(OpCode.H, 0, "h")
        circuit = _circuit("missing", 1, h)
        with self.assertRaises(MissingOperationTimingError) as ctx:
            schedule_asap(circuit, {})
        self.assertEqual(ctx.exception.operation_id, IrOperationId("sched:h"))

    def test_timing_serialization_round_trips(self) -> None:
        h = _op(OpCode.H, 0, "h")
        x = _op(OpCode.X, 0, "x")
        circuit = _circuit("serial", 1, h, x)
        profile = {IrOperationId("sched:h"): 20.0, IrOperationId("sched:x"): 10.0}
        schedule = schedule_asap(circuit, profile)
        d = schedule.to_dict()
        self.assertIn("scheduled_operations", d)
        self.assertIn("idle_intervals", d)
        self.assertIn("peak_duration_ns", d)
        self.assertEqual(json.loads(schedule.to_json()), d)

    def test_idle_interval_calculation_includes_gaps_and_tail(self) -> None:
        # q0: H at [0,20], q1: H at [0,30]; CX at [30,80]. q0 has idle [20,30].
        h0 = _op(OpCode.H, 0, "h0")
        h1 = _op(OpCode.H, 1, "h1")
        cx = _op(OpCode.CX, 1, "cx", control=0)
        circuit = _circuit("idle-calc", 2, h0, h1, cx)
        profile = {
            IrOperationId("sched:h0"): 20.0,
            IrOperationId("sched:h1"): 30.0,
            IrOperationId("sched:cx"): 50.0,
        }
        schedule = schedule_asap(circuit, profile)

        q0_intervals = schedule.idle_intervals_for_slot(0)
        # q0 is busy [0,20], then CX starts at 30 → idle [20,30]; after CX ends at 80 there's nothing → no tail
        starts = [ii.start_ns for ii in q0_intervals]
        ends = [ii.end_ns for ii in q0_intervals]
        self.assertIn(20.0, starts)
        self.assertIn(30.0, ends)

    def test_idle_interval_for_slot_with_no_operations(self) -> None:
        # A two-qubit circuit where only q0 has operations; q1 is entirely idle.
        h = _op(OpCode.H, 0, "h")
        circuit = _circuit("idle-slot", 2, h)
        profile = {IrOperationId("sched:h"): 20.0}
        schedule = schedule_asap(circuit, profile)

        q1_intervals = schedule.idle_intervals_for_slot(1)
        self.assertEqual(len(q1_intervals), 1)
        self.assertAlmostEqual(q1_intervals[0].start_ns, 0.0)
        self.assertAlmostEqual(q1_intervals[0].end_ns, 20.0)


# ---------------------------------------------------------------------------
# T1/T2 channel computation
# ---------------------------------------------------------------------------

class IdleDecoherenceChannelTests(unittest.TestCase):
    def test_zero_duration_is_identity_evolution(self) -> None:
        profile = IdleDecoherenceProfile(t1_ns=1000.0, t2_ns=500.0)
        amp, phase, gamma1, p_phi, assumptions = idle_decoherence_channels_for_duration(
            0.0, profile
        )
        self.assertIsNone(amp)
        self.assertIsNone(phase)
        self.assertEqual(gamma1, 0.0)
        self.assertEqual(p_phi, 0.0)
        self.assertTrue(any("zero" in a.lower() for a in assumptions))

    def test_t1_only_produces_amplitude_damping(self) -> None:
        t = 100.0
        t1 = 1000.0
        profile = IdleDecoherenceProfile(t1_ns=t1)
        amp, phase, gamma1, p_phi, _ = idle_decoherence_channels_for_duration(t, profile)
        expected_gamma1 = 1.0 - exp(-t / t1)
        self.assertIsNotNone(amp)
        self.assertIsNone(phase)
        self.assertAlmostEqual(gamma1, expected_gamma1)
        self.assertEqual(p_phi, 0.0)

    def test_t2_only_produces_phase_damping(self) -> None:
        t = 100.0
        t2 = 500.0
        profile = IdleDecoherenceProfile(t2_ns=t2)
        amp, phase, gamma1, p_phi, _ = idle_decoherence_channels_for_duration(t, profile)
        expected_p_phi = 1.0 - exp(-2.0 * t / t2)
        self.assertIsNone(amp)
        self.assertIsNotNone(phase)
        self.assertEqual(gamma1, 0.0)
        self.assertAlmostEqual(p_phi, expected_p_phi)

    def test_combined_t1_t2_total_coherence_decay(self) -> None:
        # Verify that combined amplitude + additional phase damping gives exp(-t/T2) coherence decay.
        t = 100.0
        t1 = 2000.0
        t2 = 800.0  # T2 < 2*T1 → valid
        profile = IdleDecoherenceProfile(t1_ns=t1, t2_ns=t2)

        amp_ch, phase_ch, gamma1, p_phi, _ = idle_decoherence_channels_for_duration(t, profile)

        # Off-diagonal decay from amplitude damping: sqrt(1 - gamma1)
        amp_coherence_factor = sqrt(1.0 - gamma1)
        # Additional phase damping: sqrt(1 - p_phi)
        phase_coherence_factor = sqrt(1.0 - p_phi)
        combined = amp_coherence_factor * phase_coherence_factor
        expected = exp(-t / t2)
        self.assertAlmostEqual(combined, expected, places=10)

    def test_t2_equals_2t1_gives_no_additional_phase_damping(self) -> None:
        t1 = 1000.0
        t2 = 2000.0  # T2 == 2*T1 → pure amplitude damping suffices
        profile = IdleDecoherenceProfile(t1_ns=t1, t2_ns=t2)
        _, phase_ch, _, p_phi, assumptions = idle_decoherence_channels_for_duration(100.0, profile)
        self.assertIsNone(phase_ch)
        self.assertEqual(p_phi, 0.0)
        self.assertTrue(any("amplitude" in a.lower() for a in assumptions))

    def test_invalid_t2_greater_than_2t1_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "t2_ns must be less than or equal to 2"):
            IdleDecoherenceProfile(t1_ns=1000.0, t2_ns=3000.0)

    def test_idle_decoherence_profile_requires_at_least_one_constant(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires t1_ns or t2_ns"):
            IdleDecoherenceProfile()

    def test_idle_decoherence_profile_to_dict(self) -> None:
        profile = IdleDecoherenceProfile(t1_ns=1000.0, t2_ns=500.0)
        d = profile.to_dict()
        self.assertEqual(d["t1_ns"], 1000.0)
        self.assertEqual(d["t2_ns"], 500.0)
        self.assertEqual(json.loads(profile.to_json()), d)


# ---------------------------------------------------------------------------
# Physical density-matrix effects
# ---------------------------------------------------------------------------

class T1DampingTests(unittest.TestCase):
    def _run_idle_t1(self, t: float, t1: float) -> tuple[tuple[tuple[complex, ...], ...], list[IdleDecoherenceEvent]]:
        """Prepare |+>, apply T1 idle for duration t, return density matrix."""
        h = _op(OpCode.H, 0, "h")
        circuit = _circuit("t1-idle", 1, h)
        profile = {IrOperationId("sched:h"): 5.0}
        schedule = schedule_asap(circuit, profile)
        idle_profile = IdleDecoherenceProfile(t1_ns=t1)
        # Create an extended schedule so q0 has idle time after the H gate.
        from ariadion_simulator.scheduling import ScheduledOperation, ExecutionSchedule, IdleInterval
        ext_peak = 5.0 + t
        ext_ops = tuple(schedule.scheduled_operations)
        ext_idle = (IdleInterval(slot=0, start_ns=5.0, end_ns=ext_peak),)
        ext_schedule = ExecutionSchedule(
            scheduled_operations=ext_ops,
            idle_intervals=ext_idle,
            peak_duration_ns=ext_peak,
        )
        request = DensityMatrixExecutionRequest(schedule=ext_schedule, idle_decoherence=idle_profile)
        result = simulate_density_matrix(circuit, execution=request)
        return result.density_matrix, list(result.idle_decoherence_events)

    def test_t1_relaxation_from_excited_state(self) -> None:
        """Apply T1 decay to |1>: population should decrease toward |0>."""
        t = 200.0
        t1 = 1000.0
        x = _op(OpCode.X, 0, "x")
        circuit = _circuit("t1-x", 1, x)
        profile = {IrOperationId("sched:x"): 5.0}
        schedule = schedule_asap(circuit, profile)
        ext_peak = 5.0 + t
        from ariadion_simulator.scheduling import ScheduledOperation, ExecutionSchedule, IdleInterval
        ext_schedule = ExecutionSchedule(
            scheduled_operations=tuple(schedule.scheduled_operations),
            idle_intervals=(IdleInterval(slot=0, start_ns=5.0, end_ns=ext_peak),),
            peak_duration_ns=ext_peak,
        )
        idle_profile = IdleDecoherenceProfile(t1_ns=t1)
        request = DensityMatrixExecutionRequest(schedule=ext_schedule, idle_decoherence=idle_profile)
        result = simulate_density_matrix(circuit, execution=request)
        dm = result.density_matrix

        gamma1 = 1.0 - exp(-t / t1)
        expected_p1 = 1.0 - gamma1  # population remaining in |1>
        self.assertAlmostEqual(dm[0][0].real, gamma1, places=10)
        self.assertAlmostEqual(dm[1][1].real, expected_p1, places=10)
        self.assertGreater(len(result.idle_decoherence_events), 0)
        event = result.idle_decoherence_events[0]
        self.assertAlmostEqual(event.amplitude_damping_probability, gamma1, places=10)

    def test_t2_coherence_loss_without_population_change(self) -> None:
        """Apply T2 (only) to |+>: off-diagonal should decay with no population change."""
        t = 100.0
        t2 = 500.0
        h = _op(OpCode.H, 0, "h")
        circuit = _circuit("t2-coherence", 1, h)
        profile = {IrOperationId("sched:h"): 5.0}
        schedule = schedule_asap(circuit, profile)
        ext_peak = 5.0 + t
        from ariadion_simulator.scheduling import ExecutionSchedule, IdleInterval
        ext_schedule = ExecutionSchedule(
            scheduled_operations=tuple(schedule.scheduled_operations),
            idle_intervals=(IdleInterval(slot=0, start_ns=5.0, end_ns=ext_peak),),
            peak_duration_ns=ext_peak,
        )
        idle_profile = IdleDecoherenceProfile(t2_ns=t2)
        request = DensityMatrixExecutionRequest(schedule=ext_schedule, idle_decoherence=idle_profile)
        result = simulate_density_matrix(circuit, execution=request)
        dm = result.density_matrix

        # Population must be unchanged (T2-only: no amplitude damping)
        self.assertAlmostEqual(dm[0][0].real, 0.5, places=10)
        self.assertAlmostEqual(dm[1][1].real, 0.5, places=10)

        # Coherence must decay as exp(-t/T2)
        expected_offdiag = 0.5 * exp(-t / t2)
        self.assertAlmostEqual(dm[0][1].real, expected_offdiag, places=10)
        self.assertAlmostEqual(dm[1][0].real, expected_offdiag, places=10)

        event = result.idle_decoherence_events[0]
        self.assertEqual(event.amplitude_damping_probability, 0.0)
        self.assertGreater(event.phase_damping_probability, 0.0)


class BellStateDegradationTests(unittest.TestCase):
    def _bell_schedule(self, idle_ns: float) -> tuple[CircuitIR, dict, object]:
        """Build a Bell-state circuit with an idle period on both qubits."""
        h = _op(OpCode.H, 0, "bell-h")
        cx = _op(OpCode.CX, 1, "bell-cx", control=0)
        circuit = _circuit("bell-idle", 2, h, cx)
        # Schedule: H from [0,20], CX from [20,70].
        # After CX ends at 70, we want idle_ns of decoherence on both qubits.
        from ariadion_simulator.scheduling import ScheduledOperation, ExecutionSchedule, IdleInterval
        sched_h = ScheduledOperation(IrOperationId("sched:bell-h"), start_ns=0.0, end_ns=20.0)
        sched_cx = ScheduledOperation(IrOperationId("sched:bell-cx"), start_ns=20.0, end_ns=70.0)
        peak = 70.0 + idle_ns
        idle_q0 = IdleInterval(slot=0, start_ns=70.0, end_ns=peak)
        idle_q1 = IdleInterval(slot=1, start_ns=70.0, end_ns=peak)
        schedule = ExecutionSchedule(
            scheduled_operations=(sched_h, sched_cx),
            idle_intervals=(idle_q0, idle_q1),
            peak_duration_ns=peak,
        )
        return circuit, {}, schedule

    def test_bell_state_degrades_under_t1_decoherence(self) -> None:
        idle_ns = 200.0
        t1 = 2000.0
        circuit, _, schedule = self._bell_schedule(idle_ns)
        idle_profile = IdleDecoherenceProfile(t1_ns=t1)
        request = DensityMatrixExecutionRequest(schedule=schedule, idle_decoherence=idle_profile)
        result = simulate_density_matrix(circuit, execution=request)

        # Without noise: Bell state has off-diagonal 0.5.
        ideal = simulate_density_matrix(circuit)

        # With T1 noise: the off-diagonal magnitude must be strictly smaller.
        ideal_offdiag = abs(ideal.density_matrix[0][3])
        noisy_offdiag = abs(result.density_matrix[0][3])
        self.assertGreater(ideal_offdiag, noisy_offdiag)
        self.assertGreater(len(result.idle_decoherence_events), 0)


# ---------------------------------------------------------------------------
# Reference / NumPy parity
# ---------------------------------------------------------------------------

class ReferenceNumpyParityTests(unittest.TestCase):
    def _t1_request(self, circuit: CircuitIR, t1_ns: float, idle_ns: float) -> DensityMatrixExecutionRequest:
        from ariadion_simulator.scheduling import ScheduledOperation, ExecutionSchedule, IdleInterval
        ops = list(circuit.operations)
        if not ops:
            schedule = ExecutionSchedule((), (), 0.0)
            return DensityMatrixExecutionRequest(
                schedule=schedule,
                idle_decoherence=IdleDecoherenceProfile(t1_ns=t1_ns),
            )
        # Assign 10ns per operation sequentially.
        sched_ops = []
        t = 0.0
        for op in ops:
            sched_ops.append(ScheduledOperation(op.id, start_ns=t, end_ns=t + 10.0))
            t += 10.0
        peak = t + idle_ns
        idle_intervals = [IdleInterval(slot=s, start_ns=t, end_ns=peak)
                          for s in range(circuit.qubit_count)]
        schedule = ExecutionSchedule(
            scheduled_operations=tuple(sched_ops),
            idle_intervals=tuple(idle_intervals),
            peak_duration_ns=peak,
        )
        return DensityMatrixExecutionRequest(
            schedule=schedule,
            idle_decoherence=IdleDecoherenceProfile(t1_ns=t1_ns),
        )

    def _assert_matrix_close(self, a: tuple, b: tuple, *, places: int = 10) -> None:
        for row_a, row_b in zip(a, b, strict=True):
            for v_a, v_b in zip(row_a, row_b, strict=True):
                self.assertAlmostEqual(v_a.real, v_b.real, places=places)
                self.assertAlmostEqual(v_a.imag, v_b.imag, places=places)

    def test_reference_and_numpy_agree_under_t1_idle_decoherence(self) -> None:
        h = _op(OpCode.H, 0, "par-h")
        x = _op(OpCode.X, 0, "par-x")
        circuit = _circuit("parity-t1", 1, h, x)
        request = self._t1_request(circuit, t1_ns=1000.0, idle_ns=50.0)

        ref = simulate_density_matrix(circuit, execution=request)
        numpy = NumpyDensityMatrixBackend().execute(circuit, options=request)
        self._assert_matrix_close(ref.density_matrix, numpy.density_matrix)
        self.assertEqual(
            len(ref.idle_decoherence_events), len(numpy.idle_decoherence_events)
        )

    def test_reference_and_numpy_agree_under_combined_t1_t2(self) -> None:
        h = _op(OpCode.H, 0, "par2-h")
        circuit = _circuit("parity-t1t2", 1, h)
        from ariadion_simulator.scheduling import ScheduledOperation, ExecutionSchedule, IdleInterval
        sched_h = ScheduledOperation(IrOperationId("sched:par2-h"), start_ns=0.0, end_ns=10.0)
        peak = 110.0
        idle = IdleInterval(slot=0, start_ns=10.0, end_ns=peak)
        schedule = ExecutionSchedule(
            scheduled_operations=(sched_h,),
            idle_intervals=(idle,),
            peak_duration_ns=peak,
        )
        request = DensityMatrixExecutionRequest(
            schedule=schedule,
            idle_decoherence=IdleDecoherenceProfile(t1_ns=2000.0, t2_ns=800.0),
        )
        ref = simulate_density_matrix(circuit, execution=request)
        numpy = NumpyDensityMatrixBackend().execute(circuit, options=request)
        self._assert_matrix_close(ref.density_matrix, numpy.density_matrix)


# ---------------------------------------------------------------------------
# Unchanged unscheduled behavior
# ---------------------------------------------------------------------------

class UnchangedUnscheduledBehaviorTests(unittest.TestCase):
    def test_ideal_circuit_without_schedule_is_unchanged(self) -> None:
        h = _op(OpCode.H, 0, "unchanged-h")
        circuit = _circuit("unchanged", 1, h)
        result = simulate_density_matrix(circuit)
        # |+> state: rho = [[0.5, 0.5], [0.5, 0.5]]
        self.assertAlmostEqual(result.density_matrix[0][0].real, 0.5)
        self.assertAlmostEqual(result.density_matrix[1][1].real, 0.5)
        self.assertEqual(result.idle_decoherence_events, ())

    def test_schedule_only_without_idle_profile_is_unchanged(self) -> None:
        h = _op(OpCode.H, 0, "sched-only-h")
        circuit = _circuit("sched-only", 1, h)
        from ariadion_simulator.scheduling import ScheduledOperation, ExecutionSchedule, IdleInterval
        schedule = ExecutionSchedule(
            scheduled_operations=(
                ScheduledOperation(IrOperationId("sched:sched-only-h"), start_ns=0.0, end_ns=10.0),
            ),
            idle_intervals=(IdleInterval(slot=0, start_ns=10.0, end_ns=60.0),),
            peak_duration_ns=60.0,
        )
        request = DensityMatrixExecutionRequest(schedule=schedule)  # no idle_decoherence
        result = simulate_density_matrix(circuit, execution=request)
        # Behavior should be identical to no-schedule ideal execution.
        ideal = simulate_density_matrix(circuit)
        for row_r, row_i in zip(result.density_matrix, ideal.density_matrix, strict=True):
            for v_r, v_i in zip(row_r, row_i, strict=True):
                self.assertAlmostEqual(v_r.real, v_i.real)
                self.assertAlmostEqual(v_r.imag, v_i.imag)
        self.assertEqual(result.idle_decoherence_events, ())


# ---------------------------------------------------------------------------
# PSD validation and performance backend audit
# ---------------------------------------------------------------------------

class DensityValidationTests(unittest.TestCase):
    def test_unphysical_matrix_raises_at_result_construction(self) -> None:
        """Full PSD validation still catches non-positive-semidefinite matrices."""
        h = _op(OpCode.H, 0, "psd-h")
        circuit = _circuit("psd-test", 1, h)
        # An explicitly non-PSD matrix (negative eigenvalue):
        # rho = [[1+epsilon, epsilon], [epsilon, -epsilon]] is non-PSD
        eps = DENSITY_MATRIX_POSITIVITY_ABS_TOLERANCE * 100
        bad_matrix: tuple = (
            ((1.0 - eps) + 0j, (1.0 + 0j)),
            ((1.0 + 0j), (-1.0 + eps) + 0j),
        )
        # Rescale to have trace 1 but keep non-PSD character
        non_psd: tuple = (
            (0.7 + 0j, 0.6 + 0j),
            (0.6 + 0j, 0.3 + 0j),
        )
        with self.assertRaises(DensityMatrixInvariantError):
            DensityMatrixResult(circuit, non_psd)

    def test_public_validate_density_matrix_catches_unphysical(self) -> None:
        non_psd = (
            (0.7 + 0j, 0.6 + 0j),
            (0.6 + 0j, 0.3 + 0j),
        )
        with self.assertRaises(DensityMatrixInvariantError):
            validate_density_matrix(non_psd, qubit_count=1)

    def test_simulation_loop_does_not_invoke_psd_per_step(self) -> None:
        """Performance backend: PSD audit runs once at result construction, not per step."""
        from ariadion_simulator import density_matrix as dm_module
        h = _op(OpCode.H, 0, "perf-h")
        x = _op(OpCode.X, 0, "perf-x")
        circuit = _circuit("perf-test", 1, h, x)
        psd_call_count = 0

        original_psd = dm_module._validate_positive_semidefinite  # noqa: SLF001

        def counting_psd(*args: object, **kwargs: object) -> None:
            nonlocal psd_call_count
            psd_call_count += 1
            return original_psd(*args, **kwargs)  # type: ignore[arg-type]

        with patch.object(dm_module, "_validate_positive_semidefinite", counting_psd):
            simulate_density_matrix(circuit)

        # PSD is called exactly once: inside DensityMatrixResult.__post_init__,
        # not for each of the 2 operations in the loop.
        self.assertEqual(psd_call_count, 1)


# ---------------------------------------------------------------------------
# SimulationCapabilities noise_features
# ---------------------------------------------------------------------------

class NoiseFeatureCapabilityTests(unittest.TestCase):
    def test_density_matrix_backends_declare_gate_and_idle_features(self) -> None:
        from ariadion_simulator import ReferenceDensityMatrixBackend
        caps = ReferenceDensityMatrixBackend().capabilities
        self.assertIn(NoiseFeature.GATE_CHANNELS, caps.noise_features)
        self.assertIn(NoiseFeature.IDLE_DECOHERENCE, caps.noise_features)
        self.assertTrue(caps.supports_noise)

    def test_state_vector_backends_declare_no_noise_features(self) -> None:
        from ariadion_simulator import ReferenceStateVectorBackend
        from ariadion_simulator_numpy import NumpyStateVectorBackend
        for backend in (ReferenceStateVectorBackend(), NumpyStateVectorBackend()):
            with self.subTest(backend=backend.backend_id):
                self.assertEqual(backend.capabilities.noise_features, ())
                self.assertFalse(backend.capabilities.supports_noise)

    def test_numpy_density_matrix_backend_declares_idle_decoherence(self) -> None:
        caps = NumpyDensityMatrixBackend().capabilities
        self.assertIn(NoiseFeature.IDLE_DECOHERENCE, caps.noise_features)
        self.assertTrue(caps.supports_noise)

    def test_capabilities_to_dict_includes_noise_features_list(self) -> None:
        from ariadion_simulator import ReferenceDensityMatrixBackend
        caps = ReferenceDensityMatrixBackend().capabilities
        d = caps.to_dict()
        self.assertIn("noise_features", d)
        self.assertNotIn("supports_noise", d)
        self.assertIn("gate_channels", d["noise_features"])
        self.assertIn("idle_decoherence", d["noise_features"])

    def test_capabilities_rejects_invalid_noise_features(self) -> None:
        with self.assertRaisesRegex(ValueError, "noise_features"):
            SimulationCapabilities(
                representations=(StateRepresentation.STATE_VECTOR,),
                queries=(SimulationQuery.FULL_STATE,),
                noise_features="not-a-tuple",  # type: ignore[arg-type]
                supports_reset=False,
                supports_sampling=False,
            )


# ---------------------------------------------------------------------------
# IdleDecoherenceEvent artifact
# ---------------------------------------------------------------------------

class IdleDecoherenceEventTests(unittest.TestCase):
    def test_event_rejects_invalid_probabilities(self) -> None:
        interval = IdleInterval(slot=0, start_ns=0.0, end_ns=10.0)
        with self.assertRaisesRegex(ValueError, "amplitude_damping_probability"):
            IdleDecoherenceEvent(
                slot=0,
                interval=interval,
                amplitude_damping_probability=1.5,
                phase_damping_probability=0.0,
                assumptions=("ok",),
            )

    def test_event_serializes_to_dict_and_json(self) -> None:
        interval = IdleInterval(slot=0, start_ns=5.0, end_ns=15.0)
        event = IdleDecoherenceEvent(
            slot=0,
            interval=interval,
            amplitude_damping_probability=0.01,
            phase_damping_probability=0.02,
            assumptions=("T1=1000ns",),
        )
        d = event.to_dict()
        self.assertEqual(d["slot"], 0)
        self.assertAlmostEqual(d["amplitude_damping_probability"], 0.01)
        self.assertAlmostEqual(d["phase_damping_probability"], 0.02)
        self.assertEqual(d["assumptions"], ["T1=1000ns"])
        self.assertEqual(json.loads(event.to_json()), d)

    def test_events_are_recorded_in_result_and_carry_interval_evidence(self) -> None:
        x = _op(OpCode.X, 0, "ev-x")
        circuit = _circuit("ev-test", 1, x)
        from ariadion_simulator.scheduling import ScheduledOperation, ExecutionSchedule, IdleInterval
        schedule = ExecutionSchedule(
            scheduled_operations=(
                ScheduledOperation(IrOperationId("sched:ev-x"), start_ns=0.0, end_ns=5.0),
            ),
            idle_intervals=(IdleInterval(slot=0, start_ns=5.0, end_ns=105.0),),
            peak_duration_ns=105.0,
        )
        profile = IdleDecoherenceProfile(t1_ns=500.0)
        request = DensityMatrixExecutionRequest(schedule=schedule, idle_decoherence=profile)
        result = simulate_density_matrix(circuit, execution=request)
        self.assertGreater(len(result.idle_decoherence_events), 0)
        event = result.idle_decoherence_events[0]
        self.assertEqual(event.slot, 0)
        self.assertAlmostEqual(event.interval.start_ns, 5.0)
        self.assertAlmostEqual(event.interval.end_ns, 105.0)
        self.assertGreater(event.amplitude_damping_probability, 0.0)


if __name__ == "__main__":
    unittest.main()
