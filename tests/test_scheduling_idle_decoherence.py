"""Hardening regressions for scheduled idle decoherence execution."""

from __future__ import annotations

import json
import unittest
from math import exp, isclose
from unittest.mock import patch

from ariadion_core import IrOperationId, ProgramId
from ariadion_ir import CircuitIR, OpCode, Operation
from ariadion_noise import IdleDecoherenceProfile
from ariadion_simulator import (
    DensityMatrixExecutionRequest,
    DensityMatrixInvariantError,
    DensityMatrixResult,
    ExecutionSchedule,
    IdleDecoherenceEvent,
    IdleDecoherenceProvenance,
    IdleInterval,
    ScheduleCircuitBindingError,
    ScheduledOperation,
    SchedulingInvariantError,
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
) -> Operation:
    return Operation(
        opcode,
        (target,),
        IrOperationId(f"sched:{name}"),
        controls=() if control is None else (control,),
    )


def _circuit(
    program_id: str,
    name: str,
    qubit_count: int,
    operations: tuple[Operation, ...],
) -> CircuitIR:
    return CircuitIR(ProgramId(program_id), name, qubit_count, operations)


def _execution_schedule_for(circuit: CircuitIR, duration_ns: float = 10.0) -> ExecutionSchedule:
    profile = {operation.id: duration_ns for operation in circuit.operations}
    return schedule_asap(circuit, profile)


class RequestPairingTests(unittest.TestCase):
    def test_rejects_schedule_without_idle_profile(self) -> None:
        circuit = _circuit("pair:a", "pair-a", 1, (_op(OpCode.H, 0, "h"),))
        schedule = _execution_schedule_for(circuit)
        with self.assertRaisesRegex(ValueError, "must be supplied together"):
            DensityMatrixExecutionRequest(schedule=schedule)

    def test_rejects_idle_profile_without_schedule(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be supplied together"):
            DensityMatrixExecutionRequest(idle_decoherence=IdleDecoherenceProfile(t1_ns=1000.0))


class ScheduleIntegrityTests(unittest.TestCase):
    def test_execution_schedule_rejects_duplicate_scheduled_operation_ids(self) -> None:
        program_id = ProgramId("sched:dup")
        duplicate_id = IrOperationId("sched:op")
        with self.assertRaisesRegex(SchedulingInvariantError, "duplicate"):
            ExecutionSchedule(
                program_id=program_id,
                scheduled_operations=(
                    ScheduledOperation(duplicate_id, 0.0, 10.0),
                    ScheduledOperation(duplicate_id, 10.0, 20.0),
                ),
                idle_intervals=(),
                peak_duration_ns=20.0,
            )

    def test_execution_schedule_rejects_idle_interval_beyond_peak(self) -> None:
        with self.assertRaisesRegex(SchedulingInvariantError, "peak_duration_ns"):
            ExecutionSchedule(
                program_id=ProgramId("sched:peak"),
                scheduled_operations=(ScheduledOperation(IrOperationId("sched:op"), 0.0, 10.0),),
                idle_intervals=(IdleInterval(slot=0, start_ns=10.0, end_ns=15.0),),
                peak_duration_ns=12.0,
            )

    def test_rejects_missing_scheduled_operation(self) -> None:
        h = _op(OpCode.H, 0, "h")
        x = _op(OpCode.X, 0, "x")
        circuit = _circuit("sched:missing", "missing", 1, (h, x))
        schedule = ExecutionSchedule(
            program_id=circuit.id,
            scheduled_operations=(ScheduledOperation(h.id, 0.0, 10.0),),
            idle_intervals=(IdleInterval(slot=0, start_ns=10.0, end_ns=20.0),),
            peak_duration_ns=20.0,
        )
        request = DensityMatrixExecutionRequest(
            schedule=schedule,
            idle_decoherence=IdleDecoherenceProfile(t1_ns=1000.0),
        )
        with self.assertRaisesRegex(ScheduleCircuitBindingError, "missing IDs"):
            simulate_density_matrix(circuit, execution=request)

    def test_rejects_extra_scheduled_operation(self) -> None:
        h = _op(OpCode.H, 0, "h")
        circuit = _circuit("sched:extra", "extra", 1, (h,))
        schedule = ExecutionSchedule(
            program_id=circuit.id,
            scheduled_operations=(
                ScheduledOperation(h.id, 0.0, 10.0),
                ScheduledOperation(IrOperationId("sched:not-in-circuit"), 10.0, 20.0),
            ),
            idle_intervals=(),
            peak_duration_ns=20.0,
        )
        request = DensityMatrixExecutionRequest(
            schedule=schedule,
            idle_decoherence=IdleDecoherenceProfile(t2_ns=500.0),
        )
        with self.assertRaisesRegex(ScheduleCircuitBindingError, "extra IDs"):
            simulate_density_matrix(circuit, execution=request)

    def test_rejects_schedule_from_another_program(self) -> None:
        h_a = _op(OpCode.H, 0, "h")
        circuit_a = _circuit("sched:program-a", "a", 1, (h_a,))
        schedule_a = _execution_schedule_for(circuit_a)

        # Same operation ID shape but different program identity.
        h_b = _op(OpCode.H, 0, "h")
        circuit_b = _circuit("sched:program-b", "b", 1, (h_b,))
        request = DensityMatrixExecutionRequest(
            schedule=schedule_a,
            idle_decoherence=IdleDecoherenceProfile(t1_ns=1000.0),
        )
        with self.assertRaisesRegex(ScheduleCircuitBindingError, "program_id"):
            simulate_density_matrix(circuit_b, execution=request)

    def test_rejects_stale_schedule_after_circuit_changes(self) -> None:
        base = _circuit(
            "sched:stale",
            "stale",
            1,
            (_op(OpCode.H, 0, "h"),),
        )
        stale_schedule = _execution_schedule_for(base)

        changed = _circuit(
            "sched:stale",
            "stale",
            1,
            (_op(OpCode.H, 0, "h"), _op(OpCode.X, 0, "x")),
        )
        request = DensityMatrixExecutionRequest(
            schedule=stale_schedule,
            idle_decoherence=IdleDecoherenceProfile(t1_ns=1000.0),
        )
        with self.assertRaisesRegex(ScheduleCircuitBindingError, "missing IDs"):
            simulate_density_matrix(changed, execution=request)


class NumericalEdgeTests(unittest.TestCase):
    def test_short_duration_limits(self) -> None:
        profile = IdleDecoherenceProfile(t1_ns=1_000_000.0, t2_ns=500_000.0)
        amp, phase, gamma1, p_phi, _assumptions, provenance = idle_decoherence_channels_for_duration(
            1e-9,
            profile,
        )
        self.assertGreaterEqual(gamma1, 0.0)
        self.assertGreaterEqual(p_phi, 0.0)
        self.assertLess(gamma1, 1e-12)
        self.assertLess(p_phi, 1e-12)
        self.assertIn(provenance.mode, {"t1_t2_combined", "t1_t2_boundary"})
        self.assertTrue(amp is None or amp.probability >= 0.0)
        self.assertTrue(phase is None or phase.probability >= 0.0)

    def test_long_duration_limits(self) -> None:
        profile = IdleDecoherenceProfile(t1_ns=1000.0, t2_ns=500.0)
        _amp, _phase, gamma1, p_phi, _assumptions, _provenance = idle_decoherence_channels_for_duration(
            1_000_000.0,
            profile,
        )
        self.assertGreater(gamma1, 0.999)
        self.assertGreater(p_phi, 0.999)
        self.assertLessEqual(gamma1, 1.0)
        self.assertLessEqual(p_phi, 1.0)

    def test_t2_equal_2t1_boundary(self) -> None:
        t1 = 1000.0
        t2 = 2 * t1
        _amp, phase, _gamma1, p_phi, _assumptions, provenance = idle_decoherence_channels_for_duration(
            100.0,
            IdleDecoherenceProfile(t1_ns=t1, t2_ns=t2),
        )
        self.assertIsNone(phase)
        self.assertEqual(p_phi, 0.0)
        self.assertEqual(provenance.mode, "t1_t2_boundary")
        self.assertEqual(provenance.tphi_inverse_per_ns, 0.0)

    def test_t2_near_2t1_combined_mode(self) -> None:
        t1 = 1000.0
        t2 = 1999.0
        _amp, _phase, gamma1, p_phi, _assumptions, provenance = idle_decoherence_channels_for_duration(
            100.0,
            IdleDecoherenceProfile(t1_ns=t1, t2_ns=t2),
        )
        self.assertEqual(provenance.mode, "t1_t2_combined")
        self.assertIsNotNone(provenance.tphi_inverse_per_ns)
        self.assertGreaterEqual(gamma1, 0.0)
        self.assertLessEqual(gamma1, 1.0)
        self.assertGreaterEqual(p_phi, 0.0)
        self.assertLessEqual(p_phi, 1.0)

    def test_combined_coherence_matches_exp_minus_t_over_t2(self) -> None:
        t = 100.0
        t1 = 2000.0
        t2 = 800.0
        _amp, _phase, gamma1, p_phi, _assumptions, _provenance = idle_decoherence_channels_for_duration(
            t,
            IdleDecoherenceProfile(t1_ns=t1, t2_ns=t2),
        )
        coherence_factor = ((1.0 - gamma1) ** 0.5) * ((1.0 - p_phi) ** 0.5)
        self.assertTrue(isclose(coherence_factor, exp(-t / t2), rel_tol=0.0, abs_tol=1e-12))


class ProvenanceTests(unittest.TestCase):
    def test_idle_event_includes_structured_provenance(self) -> None:
        interval = IdleInterval(slot=0, start_ns=5.0, end_ns=25.0)
        event = IdleDecoherenceEvent(
            slot=0,
            interval=interval,
            amplitude_damping_probability=0.01,
            phase_damping_probability=0.02,
            assumptions=("assumption",),
            provenance=IdleDecoherenceProvenance(
                mode="t1_t2_combined",
                t1_ns=1000.0,
                t2_ns=500.0,
                tphi_inverse_per_ns=0.001,
            ),
        )
        as_dict = event.to_dict()
        self.assertIn("provenance", as_dict)
        self.assertEqual(as_dict["provenance"]["mode"], "t1_t2_combined")
        self.assertEqual(json.loads(event.to_json()), as_dict)


class TrustedValidationCostTests(unittest.TestCase):
    def test_numpy_trusted_result_path_skips_full_psd_audit(self) -> None:
        from ariadion_simulator import density_matrix as density_module

        h = _op(OpCode.H, 0, "h")
        circuit = _circuit("sched:numpy-trusted", "trusted", 1, (h,))

        calls = 0
        original = density_module._validate_positive_semidefinite  # noqa: SLF001

        def counting_psd(*args: object, **kwargs: object) -> None:
            nonlocal calls
            calls += 1
            return original(*args, **kwargs)  # type: ignore[arg-type]

        with patch.object(density_module, "_validate_positive_semidefinite", counting_psd):
            NumpyDensityMatrixBackend().execute(circuit)

        self.assertEqual(calls, 0)

    def test_public_density_result_construction_still_runs_full_audit(self) -> None:
        circuit = _circuit("sched:public-audit", "public", 1, (_op(OpCode.H, 0, "h"),))
        non_psd = (
            (0.7 + 0j, 0.6 + 0j),
            (0.6 + 0j, 0.3 + 0j),
        )
        with self.assertRaises(DensityMatrixInvariantError):
            DensityMatrixResult(circuit, non_psd)

    def test_explicit_validate_density_matrix_still_rejects_non_psd(self) -> None:
        non_psd = (
            (0.7 + 0j, 0.6 + 0j),
            (0.6 + 0j, 0.3 + 0j),
        )
        with self.assertRaises(DensityMatrixInvariantError):
            validate_density_matrix(non_psd, qubit_count=1)


if __name__ == "__main__":
    unittest.main()
