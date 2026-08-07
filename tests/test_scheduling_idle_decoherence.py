"""Scheduling and idle-decoherence regression coverage.

Combines correctness hardening checks with the original scheduling/T1/T2
behavioral coverage.
"""

from __future__ import annotations

import json
import unittest
from math import exp, isclose, sqrt
from unittest.mock import patch

from ariadion_core import IrOperationId, ProgramId
from ariadion_ir import CircuitIR, OpCode, Operation
from ariadion_noise import IdleDecoherenceProfile, NoiseFeature
from ariadion_simulator import (
    DensityMatrixExecutionRequest,
    DensityMatrixInvariantError,
    DensityMatrixResult,
    ExecutionSchedule,
    IdleDecoherenceEvent,
    IdleDecoherenceProvenance,
    IdleInterval,
    MissingOperationTimingError,
    OperationTiming,
    OperationTimingError,
    ScheduleCircuitBindingError,
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


def _circuit(
    name: str,
    width: int,
    *operations: Operation,
    program_id: str | None = None,
) -> CircuitIR:
    pid = ProgramId(program_id) if program_id is not None else ProgramId(f"sched:{name}")
    return CircuitIR(pid, name, width, tuple(operations))


def _fingerprint_for(circuit: CircuitIR) -> tuple[tuple[IrOperationId, str, tuple[int, ...], tuple[int, ...]], ...]:
    return tuple(
        (
            operation.id,
            operation.opcode.value,
            tuple(operation.targets),
            tuple(operation.controls),
        )
        for operation in circuit.operations
    )


def _execution_schedule_for(circuit: CircuitIR, duration_ns: float = 10.0) -> ExecutionSchedule:
    return schedule_asap(
        circuit,
        {operation.id: duration_ns for operation in circuit.operations},
    )


class SchedulingContractTests(unittest.TestCase):
    def test_operation_timing_rejects_zero_negative_non_finite(self) -> None:
        with self.assertRaisesRegex(OperationTimingError, "positive finite"):
            OperationTiming(IrOperationId("op1"), 0.0)
        with self.assertRaisesRegex(OperationTimingError, "positive finite"):
            OperationTiming(IrOperationId("op1"), -1.0)
        with self.assertRaisesRegex(OperationTimingError, "positive finite"):
            OperationTiming(IrOperationId("op1"), float("inf"))
        with self.assertRaisesRegex(OperationTimingError, "positive finite"):
            OperationTiming(IrOperationId("op1"), float("nan"))

    def test_operation_timing_serialization(self) -> None:
        timing = OperationTiming(IrOperationId("op1"), 50.0)
        self.assertEqual(timing.operation_id, IrOperationId("op1"))
        self.assertEqual(timing.duration_ns, 50.0)
        self.assertEqual(timing.to_dict(), {"operation_id": "op1", "duration_ns": 50.0})
        self.assertEqual(json.loads(timing.to_json()), timing.to_dict())

    def test_scheduled_operation_requires_positive_duration(self) -> None:
        with self.assertRaisesRegex(SchedulingInvariantError, "greater than start_ns"):
            ScheduledOperation(IrOperationId("op1"), start_ns=10.0, end_ns=10.0)
        with self.assertRaisesRegex(SchedulingInvariantError, "greater than start_ns"):
            ScheduledOperation(IrOperationId("op1"), start_ns=10.0, end_ns=9.0)

    def test_idle_interval_requires_positive_duration(self) -> None:
        with self.assertRaisesRegex(SchedulingInvariantError, "greater than start_ns"):
            IdleInterval(slot=0, start_ns=10.0, end_ns=10.0)
        with self.assertRaisesRegex(SchedulingInvariantError, "greater than start_ns"):
            IdleInterval(slot=0, start_ns=10.0, end_ns=5.0)

    def test_execution_schedule_rejects_wrong_types_and_duplicates(self) -> None:
        with self.assertRaisesRegex(SchedulingInvariantError, "operation_fingerprint"):
            ExecutionSchedule(  # type: ignore[arg-type]
                program_id=ProgramId("sched:x"),
                operation_fingerprint=[],
                scheduled_operations=(),
                idle_intervals=(),
                peak_duration_ns=0.0,
            )
        with self.assertRaisesRegex(SchedulingInvariantError, "duplicate"):
            ExecutionSchedule(
                program_id=ProgramId("sched:x"),
                operation_fingerprint=(
                    (IrOperationId("sched:a"), "x", (0,), ()),
                    (IrOperationId("sched:a"), "x", (1,), ()),
                ),
                scheduled_operations=(
                    ScheduledOperation(IrOperationId("sched:a"), 0.0, 10.0),
                    ScheduledOperation(IrOperationId("sched:a"), 10.0, 20.0),
                ),
                idle_intervals=(),
                peak_duration_ns=20.0,
            )

    def test_schedule_asap_single_qubit_sequential(self) -> None:
        h = _op(OpCode.H, 0, "h")
        x = _op(OpCode.X, 0, "x")
        circuit = _circuit("seq", 1, h, x)
        schedule = schedule_asap(circuit, {h.id: 20.0, x.id: 10.0})

        op_h = schedule.timing_for_operation(h.id)
        op_x = schedule.timing_for_operation(x.id)
        assert op_h is not None and op_x is not None
        self.assertAlmostEqual(op_h.start_ns, 0.0)
        self.assertAlmostEqual(op_h.end_ns, 20.0)
        self.assertAlmostEqual(op_x.start_ns, 20.0)
        self.assertAlmostEqual(op_x.end_ns, 30.0)
        self.assertAlmostEqual(schedule.peak_duration_ns, 30.0)

    def test_schedule_asap_disjoint_parallel(self) -> None:
        h0 = _op(OpCode.H, 0, "h0")
        h1 = _op(OpCode.H, 1, "h1")
        circuit = _circuit("parallel", 2, h0, h1)
        schedule = schedule_asap(circuit, {h0.id: 20.0, h1.id: 30.0})

        op_h0 = schedule.timing_for_operation(h0.id)
        op_h1 = schedule.timing_for_operation(h1.id)
        assert op_h0 is not None and op_h1 is not None
        self.assertAlmostEqual(op_h0.start_ns, 0.0)
        self.assertAlmostEqual(op_h1.start_ns, 0.0)
        self.assertAlmostEqual(schedule.peak_duration_ns, 30.0)

    def test_schedule_asap_cx_waits_for_both_participants(self) -> None:
        h0 = _op(OpCode.H, 0, "h0")
        h1 = _op(OpCode.H, 1, "h1")
        cx = _op(OpCode.CX, 1, "cx", control=0)
        circuit = _circuit("cx-wait", 2, h0, h1, cx)
        schedule = schedule_asap(circuit, {h0.id: 20.0, h1.id: 30.0, cx.id: 50.0})

        op_cx = schedule.timing_for_operation(cx.id)
        assert op_cx is not None
        self.assertAlmostEqual(op_cx.start_ns, 30.0)
        self.assertAlmostEqual(op_cx.end_ns, 80.0)

    def test_schedule_asap_is_deterministic(self) -> None:
        h = _op(OpCode.H, 0, "h")
        x = _op(OpCode.X, 0, "x")
        circuit = _circuit("det", 1, h, x)
        profile = {h.id: 20.0, x.id: 10.0}
        self.assertEqual(schedule_asap(circuit, profile), schedule_asap(circuit, profile))

    def test_missing_duration_raises(self) -> None:
        h = _op(OpCode.H, 0, "h")
        circuit = _circuit("missing", 1, h)
        with self.assertRaises(MissingOperationTimingError):
            schedule_asap(circuit, {})

    def test_idle_gap_and_unused_slot_intervals(self) -> None:
        h0 = _op(OpCode.H, 0, "h0")
        h1 = _op(OpCode.H, 1, "h1")
        cx = _op(OpCode.CX, 1, "cx", control=0)
        circuit = _circuit("idle-calc", 3, h0, h1, cx)
        schedule = schedule_asap(circuit, {h0.id: 20.0, h1.id: 30.0, cx.id: 50.0})

        q0_intervals = schedule.idle_intervals_for_slot(0)
        self.assertIn(20.0, [interval.start_ns for interval in q0_intervals])
        self.assertIn(30.0, [interval.end_ns for interval in q0_intervals])

        q2_intervals = schedule.idle_intervals_for_slot(2)
        self.assertEqual(len(q2_intervals), 1)
        self.assertAlmostEqual(q2_intervals[0].start_ns, 0.0)
        self.assertAlmostEqual(q2_intervals[0].end_ns, schedule.peak_duration_ns)


class RequestPairingTests(unittest.TestCase):
    def test_rejects_schedule_without_idle_profile(self) -> None:
        h = _op(OpCode.H, 0, "h")
        circuit = _circuit("pair", 1, h)
        with self.assertRaisesRegex(ValueError, "must be supplied together"):
            DensityMatrixExecutionRequest(schedule=_execution_schedule_for(circuit))

    def test_rejects_idle_profile_without_schedule(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be supplied together"):
            DensityMatrixExecutionRequest(idle_decoherence=IdleDecoherenceProfile(t1_ns=1000.0))


class ScheduleIntegrityTests(unittest.TestCase):
    def test_rejects_missing_scheduled_operation(self) -> None:
        h = _op(OpCode.H, 0, "h")
        x = _op(OpCode.X, 0, "x")
        circuit = _circuit("missing-op", 1, h, x)
        schedule = ExecutionSchedule(
            program_id=circuit.id,
            operation_fingerprint=((h.id, h.opcode.value, h.targets, h.controls),),
            scheduled_operations=(ScheduledOperation(h.id, 0.0, 10.0),),
            idle_intervals=(IdleInterval(slot=0, start_ns=10.0, end_ns=20.0),),
            peak_duration_ns=20.0,
        )
        request = DensityMatrixExecutionRequest(schedule=schedule, idle_decoherence=IdleDecoherenceProfile(t1_ns=1000.0))
        with self.assertRaisesRegex(ScheduleCircuitBindingError, "missing IDs"):
            simulate_density_matrix(circuit, execution=request)

    def test_rejects_extra_scheduled_operation(self) -> None:
        h = _op(OpCode.H, 0, "h")
        circuit = _circuit("extra-op", 1, h)
        extra_id = IrOperationId("sched:extra")
        schedule = ExecutionSchedule(
            program_id=circuit.id,
            operation_fingerprint=(
                (h.id, h.opcode.value, h.targets, h.controls),
                (extra_id, OpCode.X.value, (0,), ()),
            ),
            scheduled_operations=(
                ScheduledOperation(h.id, 0.0, 10.0),
                ScheduledOperation(extra_id, 10.0, 20.0),
            ),
            idle_intervals=(),
            peak_duration_ns=20.0,
        )
        request = DensityMatrixExecutionRequest(schedule=schedule, idle_decoherence=IdleDecoherenceProfile(t2_ns=500.0))
        with self.assertRaisesRegex(ScheduleCircuitBindingError, "extra IDs"):
            simulate_density_matrix(circuit, execution=request)

    def test_rejects_schedule_from_another_program(self) -> None:
        h = _op(OpCode.H, 0, "h")
        circuit_a = _circuit("program-a", 1, h, program_id="sched:program-a")
        schedule_a = _execution_schedule_for(circuit_a)
        circuit_b = _circuit("program-b", 1, _op(OpCode.H, 0, "h"), program_id="sched:program-b")
        request = DensityMatrixExecutionRequest(schedule=schedule_a, idle_decoherence=IdleDecoherenceProfile(t1_ns=1000.0))
        with self.assertRaisesRegex(ScheduleCircuitBindingError, "program_id"):
            simulate_density_matrix(circuit_b, execution=request)

    def test_rejects_stale_schedule_after_circuit_operation_change(self) -> None:
        base = _circuit("stale", 1, _op(OpCode.H, 0, "h"), program_id="sched:stale")
        stale_schedule = _execution_schedule_for(base)
        changed = _circuit("stale", 1, _op(OpCode.H, 0, "h"), _op(OpCode.X, 0, "x"), program_id="sched:stale")
        request = DensityMatrixExecutionRequest(schedule=stale_schedule, idle_decoherence=IdleDecoherenceProfile(t1_ns=1000.0))
        with self.assertRaisesRegex(ScheduleCircuitBindingError, "missing IDs"):
            simulate_density_matrix(changed, execution=request)

    def test_rejects_same_ids_changed_target(self) -> None:
        # Same program ID and operation IDs; only target semantics change.
        op_a = _op(OpCode.X, 0, "a")
        op_b = _op(OpCode.X, 0, "b")
        original = _circuit("semantic-target", 2, op_a, op_b, program_id="sched:semantic")
        schedule = _execution_schedule_for(original)

        changed = _circuit(
            "semantic-target",
            2,
            _op(OpCode.X, 1, "a"),
            _op(OpCode.X, 0, "b"),
            program_id="sched:semantic",
        )
        request = DensityMatrixExecutionRequest(schedule=schedule, idle_decoherence=IdleDecoherenceProfile(t1_ns=1000.0))
        with self.assertRaisesRegex(ScheduleCircuitBindingError, "operation fingerprint"):
            simulate_density_matrix(changed, execution=request)

    def test_rejects_same_ids_changed_control_relationship(self) -> None:
        op_h = _op(OpCode.H, 0, "h")
        op_cx = _op(OpCode.CX, 1, "cx", control=0)
        original = _circuit("semantic-control", 2, op_h, op_cx, program_id="sched:semantic-control")
        schedule = _execution_schedule_for(original)

        # Same IDs but control/target semantics swapped.
        changed = _circuit(
            "semantic-control",
            2,
            _op(OpCode.H, 0, "h"),
            _op(OpCode.CX, 0, "cx", control=1),
            program_id="sched:semantic-control",
        )
        request = DensityMatrixExecutionRequest(schedule=schedule, idle_decoherence=IdleDecoherenceProfile(t1_ns=1000.0))
        with self.assertRaisesRegex(ScheduleCircuitBindingError, "operation fingerprint"):
            simulate_density_matrix(changed, execution=request)

    def test_rejects_manually_shifted_non_asap_timing(self) -> None:
        h = _op(OpCode.H, 0, "h")
        x = _op(OpCode.X, 0, "x")
        circuit = _circuit("shifted", 1, h, x)
        schedule = ExecutionSchedule(
            program_id=circuit.id,
            operation_fingerprint=_fingerprint_for(circuit),
            scheduled_operations=(
                ScheduledOperation(h.id, 0.0, 10.0),
                ScheduledOperation(x.id, 12.0, 22.0),
            ),
            idle_intervals=(IdleInterval(slot=0, start_ns=10.0, end_ns=12.0),),
            peak_duration_ns=22.0,
        )
        request = DensityMatrixExecutionRequest(schedule=schedule, idle_decoherence=IdleDecoherenceProfile(t1_ns=1000.0))
        with self.assertRaisesRegex(ScheduleCircuitBindingError, "operation timing"):
            simulate_density_matrix(circuit, execution=request)

    def test_rejects_incorrect_idle_intervals(self) -> None:
        h = _op(OpCode.H, 0, "h")
        circuit = _circuit("idle-mismatch", 2, h)
        valid = schedule_asap(circuit, {h.id: 20.0})
        # Should be slot 1 idle [0,20], make it [1,20] to mismatch while remaining structurally valid.
        wrong = ExecutionSchedule(
            program_id=valid.program_id,
            operation_fingerprint=valid.operation_fingerprint,
            scheduled_operations=valid.scheduled_operations,
            idle_intervals=(IdleInterval(slot=1, start_ns=1.0, end_ns=20.0),),
            peak_duration_ns=valid.peak_duration_ns,
        )
        request = DensityMatrixExecutionRequest(schedule=wrong, idle_decoherence=IdleDecoherenceProfile(t1_ns=1000.0))
        with self.assertRaisesRegex(ScheduleCircuitBindingError, "idle intervals"):
            simulate_density_matrix(circuit, execution=request)

    def test_rejects_inconsistent_peak_duration(self) -> None:
        h = _op(OpCode.H, 0, "h")
        circuit = _circuit("peak-mismatch", 1, h)
        with self.assertRaisesRegex(SchedulingInvariantError, "peak_duration_ns"):
            ExecutionSchedule(
                program_id=circuit.id,
                operation_fingerprint=((h.id, h.opcode.value, h.targets, h.controls),),
                scheduled_operations=(ScheduledOperation(h.id, 0.0, 10.0),),
                idle_intervals=(),
                peak_duration_ns=9.0,
            )


class IdleDecoherenceChannelTests(unittest.TestCase):
    def test_zero_duration_is_identity_evolution(self) -> None:
        profile = IdleDecoherenceProfile(t1_ns=1000.0, t2_ns=500.0)
        amp, phase, gamma1, p_phi, assumptions, provenance = idle_decoherence_channels_for_duration(0.0, profile)
        self.assertIsNone(amp)
        self.assertIsNone(phase)
        self.assertEqual(gamma1, 0.0)
        self.assertEqual(p_phi, 0.0)
        self.assertTrue(any("zero" in assumption.lower() for assumption in assumptions))
        self.assertEqual(provenance.mode, "identity")

    def test_t1_only_damping(self) -> None:
        t = 100.0
        t1 = 1000.0
        amp, phase, gamma1, p_phi, _assumptions, provenance = idle_decoherence_channels_for_duration(
            t,
            IdleDecoherenceProfile(t1_ns=t1),
        )
        self.assertIsNotNone(amp)
        self.assertIsNone(phase)
        self.assertAlmostEqual(gamma1, 1.0 - exp(-t / t1))
        self.assertEqual(p_phi, 0.0)
        self.assertEqual(provenance.mode, "t1_only")

    def test_t2_only_dephasing(self) -> None:
        t = 100.0
        t2 = 500.0
        amp, phase, gamma1, p_phi, _assumptions, provenance = idle_decoherence_channels_for_duration(
            t,
            IdleDecoherenceProfile(t2_ns=t2),
        )
        self.assertIsNone(amp)
        self.assertIsNotNone(phase)
        self.assertEqual(gamma1, 0.0)
        self.assertAlmostEqual(p_phi, 1.0 - exp(-2.0 * t / t2))
        self.assertEqual(provenance.mode, "t2_only")

    def test_combined_t1_t2_coherence_decay(self) -> None:
        t = 100.0
        t1 = 2000.0
        t2 = 800.0
        _amp, _phase, gamma1, p_phi, _assumptions, provenance = idle_decoherence_channels_for_duration(
            t,
            IdleDecoherenceProfile(t1_ns=t1, t2_ns=t2),
        )
        coherence = sqrt(1.0 - gamma1) * sqrt(1.0 - p_phi)
        self.assertAlmostEqual(coherence, exp(-t / t2), places=10)
        self.assertEqual(provenance.mode, "t1_t2_combined")

    def test_invalid_t2_greater_than_2t1(self) -> None:
        with self.assertRaisesRegex(ValueError, "less than or equal to 2"):
            IdleDecoherenceProfile(t1_ns=1000.0, t2_ns=3000.0)

    def test_numerical_edges(self) -> None:
        short = idle_decoherence_channels_for_duration(
            1e-9,
            IdleDecoherenceProfile(t1_ns=1_000_000.0, t2_ns=500_000.0),
        )
        long = idle_decoherence_channels_for_duration(
            1_000_000.0,
            IdleDecoherenceProfile(t1_ns=1000.0, t2_ns=500.0),
        )
        _amp_s, _phase_s, gamma1_s, p_phi_s, _ass_s, _prov_s = short
        _amp_l, _phase_l, gamma1_l, p_phi_l, _ass_l, _prov_l = long
        self.assertLess(gamma1_s, 1e-12)
        self.assertLess(p_phi_s, 1e-12)
        self.assertGreater(gamma1_l, 0.999)
        self.assertGreater(p_phi_l, 0.999)
        self.assertLessEqual(gamma1_l, 1.0)
        self.assertLessEqual(p_phi_l, 1.0)

    def test_t2_boundary_modes(self) -> None:
        t1 = 1000.0
        _amp, phase, _gamma1, p_phi, _ass, provenance = idle_decoherence_channels_for_duration(
            100.0,
            IdleDecoherenceProfile(t1_ns=t1, t2_ns=2 * t1),
        )
        self.assertIsNone(phase)
        self.assertEqual(p_phi, 0.0)
        self.assertEqual(provenance.mode, "t1_t2_boundary")


class PhysicalDensityEffectsTests(unittest.TestCase):
    def test_population_relaxation(self) -> None:
        t = 200.0
        t1 = 1000.0
        x = _op(OpCode.X, 0, "x")
        circuit = _circuit("t1-relax", 1, x)
        base = _execution_schedule_for(circuit, duration_ns=5.0)
        peak = 5.0 + t
        schedule = ExecutionSchedule(
            program_id=base.program_id,
            operation_fingerprint=base.operation_fingerprint,
            scheduled_operations=base.scheduled_operations,
            idle_intervals=(IdleInterval(slot=0, start_ns=5.0, end_ns=peak),),
            peak_duration_ns=peak,
        )
        result = simulate_density_matrix(
            circuit,
            execution=DensityMatrixExecutionRequest(
                schedule=schedule,
                idle_decoherence=IdleDecoherenceProfile(t1_ns=t1),
            ),
        )
        gamma1 = 1.0 - exp(-t / t1)
        self.assertAlmostEqual(result.density_matrix[0][0].real, gamma1, places=10)
        self.assertAlmostEqual(result.density_matrix[1][1].real, 1.0 - gamma1, places=10)

    def test_coherence_loss_without_population_change(self) -> None:
        t = 100.0
        t2 = 500.0
        h = _op(OpCode.H, 0, "h")
        circuit = _circuit("t2-loss", 1, h)
        base = _execution_schedule_for(circuit, duration_ns=5.0)
        peak = 5.0 + t
        schedule = ExecutionSchedule(
            program_id=base.program_id,
            operation_fingerprint=base.operation_fingerprint,
            scheduled_operations=base.scheduled_operations,
            idle_intervals=(IdleInterval(slot=0, start_ns=5.0, end_ns=peak),),
            peak_duration_ns=peak,
        )
        result = simulate_density_matrix(
            circuit,
            execution=DensityMatrixExecutionRequest(
                schedule=schedule,
                idle_decoherence=IdleDecoherenceProfile(t2_ns=t2),
            ),
        )
        expected = 0.5 * exp(-t / t2)
        self.assertAlmostEqual(result.density_matrix[0][0].real, 0.5, places=10)
        self.assertAlmostEqual(result.density_matrix[1][1].real, 0.5, places=10)
        self.assertAlmostEqual(result.density_matrix[0][1].real, expected, places=10)

    def test_bell_state_degradation(self) -> None:
        h = _op(OpCode.H, 0, "h")
        cx = _op(OpCode.CX, 1, "cx", control=0)
        circuit = _circuit("bell", 2, h, cx)
        schedule = schedule_asap(circuit, {h.id: 20.0, cx.id: 50.0})
        peak = schedule.peak_duration_ns + 200.0
        extended = ExecutionSchedule(
            program_id=schedule.program_id,
            operation_fingerprint=schedule.operation_fingerprint,
            scheduled_operations=schedule.scheduled_operations,
            idle_intervals=(
                *schedule.idle_intervals,
                IdleInterval(slot=0, start_ns=schedule.peak_duration_ns, end_ns=peak),
                IdleInterval(slot=1, start_ns=schedule.peak_duration_ns, end_ns=peak),
            ),
            peak_duration_ns=peak,
        )
        noisy = simulate_density_matrix(
            circuit,
            execution=DensityMatrixExecutionRequest(
                schedule=extended,
                idle_decoherence=IdleDecoherenceProfile(t1_ns=2000.0),
            ),
        )
        ideal = simulate_density_matrix(circuit)
        self.assertGreater(abs(ideal.density_matrix[0][3]), abs(noisy.density_matrix[0][3]))


class ReferenceNumpyParityTests(unittest.TestCase):
    def _assert_matrix_close(self, left: tuple, right: tuple, *, places: int = 10) -> None:
        for row_l, row_r in zip(left, right, strict=True):
            for value_l, value_r in zip(row_l, row_r, strict=True):
                self.assertAlmostEqual(value_l.real, value_r.real, places=places)
                self.assertAlmostEqual(value_l.imag, value_r.imag, places=places)

    def test_reference_numpy_parity_t1(self) -> None:
        h = _op(OpCode.H, 0, "h")
        x = _op(OpCode.X, 0, "x")
        circuit = _circuit("parity-t1", 1, h, x)
        schedule = schedule_asap(circuit, {h.id: 10.0, x.id: 10.0})
        peak = schedule.peak_duration_ns + 50.0
        extended = ExecutionSchedule(
            program_id=schedule.program_id,
            operation_fingerprint=schedule.operation_fingerprint,
            scheduled_operations=schedule.scheduled_operations,
            idle_intervals=(IdleInterval(slot=0, start_ns=schedule.peak_duration_ns, end_ns=peak),),
            peak_duration_ns=peak,
        )
        request = DensityMatrixExecutionRequest(
            schedule=extended,
            idle_decoherence=IdleDecoherenceProfile(t1_ns=1000.0),
        )
        reference = simulate_density_matrix(circuit, execution=request)
        numpy_result = NumpyDensityMatrixBackend().execute(circuit, options=request)
        self._assert_matrix_close(reference.density_matrix, numpy_result.density_matrix)

    def test_reference_numpy_parity_combined_t1_t2(self) -> None:
        h = _op(OpCode.H, 0, "h")
        circuit = _circuit("parity-t1t2", 1, h)
        schedule = schedule_asap(circuit, {h.id: 10.0})
        peak = schedule.peak_duration_ns + 100.0
        extended = ExecutionSchedule(
            program_id=schedule.program_id,
            operation_fingerprint=schedule.operation_fingerprint,
            scheduled_operations=schedule.scheduled_operations,
            idle_intervals=(IdleInterval(slot=0, start_ns=schedule.peak_duration_ns, end_ns=peak),),
            peak_duration_ns=peak,
        )
        request = DensityMatrixExecutionRequest(
            schedule=extended,
            idle_decoherence=IdleDecoherenceProfile(t1_ns=2000.0, t2_ns=800.0),
        )
        reference = simulate_density_matrix(circuit, execution=request)
        numpy_result = NumpyDensityMatrixBackend().execute(circuit, options=request)
        self._assert_matrix_close(reference.density_matrix, numpy_result.density_matrix)


class UnscheduledBehaviorTests(unittest.TestCase):
    def test_unscheduled_execution_unchanged(self) -> None:
        h = _op(OpCode.H, 0, "h")
        circuit = _circuit("unchanged", 1, h)
        result = simulate_density_matrix(circuit)
        self.assertAlmostEqual(result.density_matrix[0][0].real, 0.5)
        self.assertAlmostEqual(result.density_matrix[1][1].real, 0.5)
        self.assertEqual(result.idle_decoherence_events, ())


class DensityValidationTests(unittest.TestCase):
    def test_public_result_rejects_non_psd(self) -> None:
        h = _op(OpCode.H, 0, "h")
        circuit = _circuit("psd", 1, h)
        non_psd = (
            (0.7 + 0j, 0.6 + 0j),
            (0.6 + 0j, 0.3 + 0j),
        )
        with self.assertRaises(DensityMatrixInvariantError):
            DensityMatrixResult(circuit, non_psd)

    def test_explicit_validate_density_matrix_rejects_non_psd(self) -> None:
        non_psd = (
            (0.7 + 0j, 0.6 + 0j),
            (0.6 + 0j, 0.3 + 0j),
        )
        with self.assertRaises(DensityMatrixInvariantError):
            validate_density_matrix(non_psd, qubit_count=1)

    def test_numpy_trusted_result_skips_psd_audit(self) -> None:
        from ariadion_simulator import density_matrix as density_module

        h = _op(OpCode.H, 0, "h")
        circuit = _circuit("trusted", 1, h)

        call_count = 0
        original = density_module._validate_positive_semidefinite  # noqa: SLF001

        def counting_psd(*args: object, **kwargs: object) -> None:
            nonlocal call_count
            call_count += 1
            return original(*args, **kwargs)  # type: ignore[arg-type]

        with patch.object(density_module, "_validate_positive_semidefinite", counting_psd):
            NumpyDensityMatrixBackend().execute(circuit)

        self.assertEqual(call_count, 0)


class CapabilityBehaviorTests(unittest.TestCase):
    def test_density_backends_declare_gate_and_idle_noise_features(self) -> None:
        from ariadion_simulator import ReferenceDensityMatrixBackend

        capabilities = ReferenceDensityMatrixBackend().capabilities
        self.assertIn(NoiseFeature.GATE_CHANNELS, capabilities.noise_features)
        self.assertIn(NoiseFeature.IDLE_DECOHERENCE, capabilities.noise_features)
        self.assertTrue(capabilities.supports_noise)

    def test_statevector_backends_declare_no_noise_features(self) -> None:
        from ariadion_simulator import ReferenceStateVectorBackend
        from ariadion_simulator_numpy import NumpyStateVectorBackend

        for backend in (ReferenceStateVectorBackend(), NumpyStateVectorBackend()):
            with self.subTest(backend=backend.backend_id):
                self.assertEqual(backend.capabilities.noise_features, ())
                self.assertFalse(backend.capabilities.supports_noise)

    def test_capabilities_to_dict_includes_noise_features(self) -> None:
        from ariadion_simulator import ReferenceDensityMatrixBackend

        capabilities = ReferenceDensityMatrixBackend().capabilities
        serialized = capabilities.to_dict()
        self.assertIn("noise_features", serialized)
        self.assertNotIn("supports_noise", serialized)

    def test_capabilities_reject_invalid_noise_features(self) -> None:
        with self.assertRaisesRegex(ValueError, "noise_features"):
            SimulationCapabilities(
                representations=(StateRepresentation.STATE_VECTOR,),
                queries=(SimulationQuery.FULL_STATE,),
                noise_features="not-a-tuple",  # type: ignore[arg-type]
                supports_reset=False,
                supports_sampling=False,
            )


class IdleEventArtifactTests(unittest.TestCase):
    def test_event_rejects_invalid_probabilities(self) -> None:
        interval = IdleInterval(slot=0, start_ns=0.0, end_ns=10.0)
        with self.assertRaisesRegex(ValueError, "amplitude_damping_probability"):
            IdleDecoherenceEvent(
                slot=0,
                interval=interval,
                amplitude_damping_probability=1.5,
                phase_damping_probability=0.0,
                assumptions=("ok",),
                provenance=IdleDecoherenceProvenance(
                    mode="t1_only",
                    t1_ns=1000.0,
                    t2_ns=None,
                    tphi_inverse_per_ns=None,
                ),
            )

    def test_event_serialization_includes_provenance(self) -> None:
        interval = IdleInterval(slot=0, start_ns=5.0, end_ns=15.0)
        event = IdleDecoherenceEvent(
            slot=0,
            interval=interval,
            amplitude_damping_probability=0.01,
            phase_damping_probability=0.02,
            assumptions=("T1=1000ns",),
            provenance=IdleDecoherenceProvenance(
                mode="t1_t2_combined",
                t1_ns=1000.0,
                t2_ns=500.0,
                tphi_inverse_per_ns=0.001,
            ),
        )
        data = event.to_dict()
        self.assertIn("provenance", data)
        self.assertEqual(json.loads(event.to_json()), data)


if __name__ == "__main__":
    unittest.main()
