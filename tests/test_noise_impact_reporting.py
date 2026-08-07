from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import unittest
from math import exp

from ariadion import Bit, Qubit, cx, h, quantum, x
from ariadion_core import IrOperationId, ProgramId
from ariadion_ir import CircuitIR, OpCode, Operation
from ariadion_noise import (
    AmplitudeDampingChannel,
    BinaryReadoutChannel,
    BitFlipChannel,
    ExecutableNoiseModel,
    GateChannelBinding,
    IdleDecoherenceProfile,
    OneQubitGate,
)
from ariadion_runtime import build_density_noise_impact_report, run_logical_module
from ariadion_simulator import (
    DensityMatrixExecutionRequest,
    schedule_asap,
    simulate_density_matrix,
)
from theonoe import (
    BinaryReadoutChannelSnapshot,
    IdleDecoherenceProfileSnapshot,
    MetricProvenance,
    NoiseImpactBaselineMode,
    NoiseImpactComparisonProvenance,
    NoiseImpactEventKind,
    NoiseImpactEventFinding,
    NoiseImpactMetric,
    NoiseImpactScheduleSummary,
    NoiseImpactScope,
    build_noise_impact_report,
    inspect_density_state,
)
from daidalon import compile_logical_module

try:
    from ariadion_simulator_numpy import NumpyDensityMatrixBackend

    HAS_NUMPY_SIMULATOR = True
except ModuleNotFoundError:  # pragma: no cover - exercised in dependency-minimal CI
    NumpyDensityMatrixBackend = None  # type: ignore[assignment]
    HAS_NUMPY_SIMULATOR = False


@quantum
def _return_one() -> Bit:
    q = Qubit()
    x(q)
    return q


@quantum
def _return_quantum() -> Qubit:
    q = Qubit()
    h(q)
    return q


@quantum
def _idle_sensitive_classical() -> Bit:
    left = Qubit()
    right = Qubit()
    h(left)
    cx(left, right)
    x(right)
    return left


def _op(name: str) -> Operation:
    return Operation(OpCode.X, (0,), IrOperationId(f"noise-impact:{name}"))


def _two_qubit_idle_circuit() -> CircuitIR:
    h = Operation(OpCode.H, (0,), IrOperationId("noise-impact:idle-h"))
    x_other = Operation(OpCode.X, (1,), IrOperationId("noise-impact:idle-x"))
    return CircuitIR(ProgramId("noise-impact:idle"), "noise-impact-idle", 2, (h, x_other))


class GateNoiseEvidenceTests(unittest.TestCase):
    def test_reference_density_result_records_gate_noise_application_events(self) -> None:
        circuit = CircuitIR(ProgramId("noise-impact:gate"), "noise-impact-gate", 1, (_op("gate-x"),))
        request = DensityMatrixExecutionRequest(
            ExecutableNoiseModel(
                gate_channels=(
                    GateChannelBinding(OneQubitGate.X, BitFlipChannel(0.25)),
                )
            )
        )

        result = simulate_density_matrix(circuit, execution=request)
        self.assertEqual(len(result.gate_noise_events), 1)
        event = result.gate_noise_events[0]
        self.assertEqual(event.operation_id, IrOperationId("noise-impact:gate-x"))
        self.assertEqual(event.target_slot, 0)
        self.assertEqual(event.gate, OneQubitGate.X)
        self.assertEqual(event.application_order, 0)
        self.assertEqual(event.application_ordering, "ideal_then_channel")
        self.assertEqual(event.channel.to_dict()["kind"], "bit_flip")

    @unittest.skipUnless(HAS_NUMPY_SIMULATOR, "requires optional NumPy simulator backend")
    def test_numpy_density_reports_same_gate_noise_event_sequence(self) -> None:
        circuit = CircuitIR(ProgramId("noise-impact:gate"), "noise-impact-gate", 1, (_op("gate-x"),))
        request = DensityMatrixExecutionRequest(
            ExecutableNoiseModel(
                gate_channels=(
                    GateChannelBinding(OneQubitGate.X, BitFlipChannel(0.25)),
                )
            )
        )

        reference = simulate_density_matrix(circuit, execution=request)
        assert NumpyDensityMatrixBackend is not None
        numpy_result = NumpyDensityMatrixBackend().execute(circuit, options=request)
        self.assertEqual(
            tuple(event.to_dict() for event in reference.gate_noise_events),
            tuple(event.to_dict() for event in numpy_result.gate_noise_events),
        )


class NoiseImpactReportTests(unittest.TestCase):
    def _metric_map(self, report: object) -> dict[str, object]:
        assert hasattr(report, "metrics")
        return {metric.name: metric for metric in report.metrics}

    def _metric_value(self, report: object, name: str) -> float:
        metric_by_name = self._metric_map(report)
        assert name in metric_by_name
        metric = metric_by_name[name]
        return metric.value

    def _scheduled_idle_request_for_module(self) -> DensityMatrixExecutionRequest:
        compilation = compile_logical_module(_idle_sensitive_classical.to_logical_module())
        durations = {
            operation.id: 10.0
            for operation in compilation.ir.operations
        }
        for operation in compilation.ir.operations:
            if operation.opcode is OpCode.X and operation.targets == (1,):
                durations[operation.id] = 120.0
        schedule = schedule_asap(compilation.ir, durations)
        return DensityMatrixExecutionRequest(
            schedule=schedule,
            idle_decoherence=IdleDecoherenceProfile(t2_ns=600.0),
        )

    def test_runtime_helper_accepts_no_external_execution_or_backend_arguments(self) -> None:
        run = run_logical_module(
            _return_one.to_logical_module(),
            execution=DensityMatrixExecutionRequest(),
        )
        with self.assertRaises(TypeError):
            build_density_noise_impact_report(run, execution=DensityMatrixExecutionRequest())  # type: ignore[call-arg]
        with self.assertRaises(TypeError):
            build_density_noise_impact_report(run, backend_id="forged")  # type: ignore[call-arg]

    def test_runtime_helper_reports_zero_deltas_without_noise(self) -> None:
        run = run_logical_module(
            _return_one.to_logical_module(),
            execution=DensityMatrixExecutionRequest(),
        )

        report = build_density_noise_impact_report(run)
        self.assertAlmostEqual(self._metric_value(report, "hilbert_schmidt_distance"), 0.0)
        self.assertAlmostEqual(self._metric_value(report, "physical_output_tvd"), 0.0)
        self.assertAlmostEqual(self._metric_value(report, "readout_distortion_tvd"), 0.0)
        self.assertEqual(report.event_findings, ())

    def test_runtime_helper_separates_physical_state_and_readout_distortion(self) -> None:
        request = DensityMatrixExecutionRequest(
            ExecutableNoiseModel(
                gate_channels=(
                    GateChannelBinding(OneQubitGate.X, BitFlipChannel(0.3)),
                ),
                readout_channel=BinaryReadoutChannel(0.1, 0.2),
            )
        )
        run = run_logical_module(_return_one.to_logical_module(), execution=request)
        report = build_density_noise_impact_report(run)

        self.assertGreater(self._metric_value(report, "physical_output_tvd"), 0.0)
        self.assertGreater(self._metric_value(report, "readout_distortion_tvd"), 0.0)

        finding_kinds = tuple(finding.kind for finding in report.event_findings)
        self.assertIn(NoiseImpactEventKind.GATE_CHANNEL, finding_kinds)
        self.assertIn(NoiseImpactEventKind.READOUT_DISTORTION, finding_kinds)

    def test_provenance_is_bound_to_run_execution_request(self) -> None:
        request = self._scheduled_idle_request_for_module()
        run = run_logical_module(_idle_sensitive_classical.to_logical_module(), execution=request)
        report = build_density_noise_impact_report(run)

        self.assertEqual(report.comparison.noisy_backend_id, "reference-density-matrix")
        self.assertEqual(report.comparison.ideal_backend_id, "reference-density-matrix")
        self.assertEqual(
            report.comparison.ideal_baseline_mode,
            NoiseImpactBaselineMode.IDEAL_NOISE_DISABLED_REPLAY,
        )
        self.assertIsNotNone(report.comparison.noisy_schedule)
        assert report.comparison.noisy_schedule is not None
        assert request.schedule is not None
        self.assertEqual(
            report.comparison.noisy_schedule.operation_fingerprint,
            run.provenance.schedule.operation_fingerprint if run.provenance.schedule is not None else (),
        )
        self.assertEqual(
            report.comparison.noisy_schedule.peak_duration_ns,
            run.provenance.schedule.peak_duration_ns if run.provenance.schedule is not None else 0.0,
        )
        self.assertEqual(
            report.comparison.noisy_idle_decoherence,
            IdleDecoherenceProfileSnapshot(
                t1_ns=request.idle_decoherence.t1_ns if request.idle_decoherence is not None else None,
                t2_ns=request.idle_decoherence.t2_ns if request.idle_decoherence is not None else None,
            ) if request.idle_decoherence is not None else None,
        )

    def test_runtime_helper_cannot_fabricate_readout_or_gate_provenance(self) -> None:
        request = DensityMatrixExecutionRequest(
            ExecutableNoiseModel(
                gate_channels=(
                    GateChannelBinding(OneQubitGate.X, BitFlipChannel(0.25)),
                ),
                readout_channel=BinaryReadoutChannel(0.1, 0.2),
            )
        )
        run = run_logical_module(_return_one.to_logical_module(), execution=request)
        report = build_density_noise_impact_report(run)

        gate_findings = [
            finding
            for finding in report.event_findings
            if finding.kind is NoiseImpactEventKind.GATE_CHANNEL
        ]
        readout_findings = [
            finding
            for finding in report.event_findings
            if finding.kind is NoiseImpactEventKind.READOUT_DISTORTION
        ]
        self.assertEqual(len(gate_findings), 1)
        self.assertEqual(gate_findings[0].gate.channel.to_dict()["kind"], "bit_flip")
        self.assertEqual(len(readout_findings), 1)
        self.assertEqual(readout_findings[0].readout.channel.to_dict()["kind"], "binary_readout")

    def test_quantum_only_reports_omit_output_distribution_metrics(self) -> None:
        request = DensityMatrixExecutionRequest(
            ExecutableNoiseModel(readout_channel=BinaryReadoutChannel(0.1, 0.2))
        )
        run = run_logical_module(_return_quantum.to_logical_module(), execution=request)
        report = build_density_noise_impact_report(run)

        metric_names = set(self._metric_map(report))
        self.assertNotIn("physical_output_tvd", metric_names)
        self.assertNotIn("readout_distortion_tvd", metric_names)
        self.assertIsNone(report.ideal_physical_distribution)
        self.assertIsNone(report.noisy_physical_distribution)
        self.assertIsNone(report.reported_distribution)
        finding_kinds = {finding.kind for finding in report.event_findings}
        self.assertNotIn(NoiseImpactEventKind.READOUT_DISTORTION, finding_kinds)

    def test_classical_output_metrics_present_even_when_zero(self) -> None:
        run = run_logical_module(
            _return_one.to_logical_module(),
            execution=DensityMatrixExecutionRequest(),
        )
        report = build_density_noise_impact_report(run)
        self.assertAlmostEqual(self._metric_value(report, "physical_output_tvd"), 0.0)
        self.assertAlmostEqual(self._metric_value(report, "readout_distortion_tvd"), 0.0)

    def test_runtime_helper_idle_only_behavior(self) -> None:
        run = run_logical_module(
            _idle_sensitive_classical.to_logical_module(),
            execution=self._scheduled_idle_request_for_module(),
        )
        report = build_density_noise_impact_report(run)
        self.assertGreater(self._metric_value(report, "hilbert_schmidt_distance"), 0.0)
        finding_kinds = {finding.kind for finding in report.event_findings}
        self.assertIn(NoiseImpactEventKind.IDLE_DECOHERENCE, finding_kinds)
        self.assertNotIn(NoiseImpactEventKind.GATE_CHANNEL, finding_kinds)

    def test_all_numerical_metrics_are_derived_and_event_evidence_observed(self) -> None:
        request = DensityMatrixExecutionRequest(
            ExecutableNoiseModel(
                gate_channels=(
                    GateChannelBinding(OneQubitGate.X, BitFlipChannel(0.25)),
                ),
                readout_channel=BinaryReadoutChannel(0.1, 0.2),
            )
        )
        run = run_logical_module(_return_one.to_logical_module(), execution=request)
        report = build_density_noise_impact_report(run)

        for metric in report.metrics:
            self.assertEqual(metric.provenance, MetricProvenance.DERIVED)
            self.assertNotEqual(metric.provenance, MetricProvenance.COUNTERFACTUAL)
        for finding in report.event_findings:
            self.assertEqual(finding.provenance, MetricProvenance.OBSERVED)

    def test_public_density_input_rejects_non_hermitian_matrix(self) -> None:
        with self.assertRaisesRegex(ValueError, "Hermitian"):
            inspect_density_state(
                (
                    (0.5 + 0j, 0.25 + 0.2j),
                    (0.25 + 0.2j, 0.5 + 0j),
                ),
                qubit_count=1,
            )

    def test_public_density_input_rejects_non_unit_trace_matrix(self) -> None:
        with self.assertRaisesRegex(ValueError, "trace"):
            inspect_density_state(
                (
                    (0.6 + 0j, 0j),
                    (0j, 0.6 + 0j),
                ),
                qubit_count=1,
            )

    def test_public_density_input_rejects_non_psd_high_dimensional_case(self) -> None:
        with self.assertRaisesRegex(ValueError, "positive semidefinite"):
            inspect_density_state(
                (
                    (0.5 + 0j, 0.0 + 0j, 0.5 + 0j, 0.0 + 0j),
                    (0.0 + 0j, -0.01 + 0j, 0.0 + 0j, 0.0 + 0j),
                    (0.5 + 0j, 0.0 + 0j, 0.51 + 0j, 0.0 + 0j),
                    (0.0 + 0j, 0.0 + 0j, 0.0 + 0j, 0.0 + 0j),
                ),
                qubit_count=2,
            )

    def test_inspect_density_state_accepts_real_numeric_entries(self) -> None:
        report = inspect_density_state(
            (
                (1.0, 0.0),
                (0.0, 0.0),
            ),
            qubit_count=1,
        )
        self.assertAlmostEqual(report.purity, 1.0)
        self.assertAlmostEqual(report.l1_coherence, 0.0)

    def test_invalid_distribution_inputs_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "sum to one"):
            build_noise_impact_report(
                comparison=NoiseImpactComparisonProvenance(
                    circuit_id=ProgramId("noise-impact:bad-dist"),
                    representation="density_matrix",
                    noisy_backend_id="reference-density-matrix",
                    ideal_backend_id="reference-density-matrix",
                    ideal_baseline_mode=NoiseImpactBaselineMode.IDEAL_NOISE_DISABLED_REPLAY,
                    noisy_schedule=None,
                    noisy_idle_decoherence=None,
                    ideal_baseline_derivation="test",
                ),
                ideal_density_matrix=((1 + 0j, 0j), (0j, 0j)),
                noisy_density_matrix=((1 + 0j, 0j), (0j, 0j)),
                qubit_count=1,
                ideal_physical_distribution=(1.0, 0.0),
                noisy_physical_distribution=(0.6, 0.1),
                reported_distribution=(0.6, 0.4),
            )

    def test_supported_runtime_construction_rejects_provenance_circuit_mismatch(self) -> None:
        run = run_logical_module(
            _return_one.to_logical_module(),
            execution=DensityMatrixExecutionRequest(),
        )
        with self.assertRaisesRegex(ValueError, "provenance circuit_id"):
            replace(
                run,
                provenance=replace(
                    run.provenance,
                    circuit_id=ProgramId("noise-impact:forged-circuit"),
                ),
            )

    def test_supported_runtime_construction_rejects_readout_policy_mismatch(self) -> None:
        request = DensityMatrixExecutionRequest(
            ExecutableNoiseModel(readout_channel=BinaryReadoutChannel(0.1, 0.2))
        )
        run = run_logical_module(_return_one.to_logical_module(), execution=request)
        with self.assertRaisesRegex(ValueError, "without readout noise"):
            replace(
                run,
                provenance=replace(run.provenance, readout_channel=None),
            )

    def test_event_findings_reject_missing_extra_and_mismatched_evidence(self) -> None:
        with self.assertRaisesRegex(ValueError, "exactly one"):
            NoiseImpactEventFinding(
                kind=NoiseImpactEventKind.GATE_CHANNEL,
                provenance=MetricProvenance.OBSERVED,
                summary="bad",
            )
        run = run_logical_module(
            _return_one.to_logical_module(),
            execution=DensityMatrixExecutionRequest(
                ExecutableNoiseModel(
                    gate_channels=(
                        GateChannelBinding(OneQubitGate.X, BitFlipChannel(0.2)),
                    )
                )
            ),
        )
        report = build_density_noise_impact_report(run)
        gate_finding = next(
            finding
            for finding in report.event_findings
            if finding.kind is NoiseImpactEventKind.GATE_CHANNEL
        )
        readout_run = run_logical_module(
            _return_one.to_logical_module(),
            execution=DensityMatrixExecutionRequest(
                ExecutableNoiseModel(readout_channel=BinaryReadoutChannel(0.1, 0.2))
            ),
        )
        readout_report = build_density_noise_impact_report(readout_run)
        readout_finding = next(
            finding
            for finding in readout_report.event_findings
            if finding.kind is NoiseImpactEventKind.READOUT_DISTORTION
        )
        with self.assertRaisesRegex(ValueError, "exactly one event evidence"):
            NoiseImpactEventFinding(
                kind=NoiseImpactEventKind.GATE_CHANNEL,
                provenance=MetricProvenance.OBSERVED,
                summary="bad",
                gate=gate_finding.gate,
                readout=readout_finding.readout,
            )

    def test_duplicate_metric_names_are_rejected(self) -> None:
        run = run_logical_module(
            _return_one.to_logical_module(),
            execution=DensityMatrixExecutionRequest(),
        )
        report = build_density_noise_impact_report(run)
        with self.assertRaisesRegex(ValueError, "unique"):
            replace(report, metrics=report.metrics + (report.metrics[0],))

    def test_schedule_and_circuit_identity_mismatch_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "program_id"):
            NoiseImpactComparisonProvenance(
                circuit_id=ProgramId("noise-impact:circuit-a"),
                representation="density_matrix",
                noisy_backend_id="reference-density-matrix",
                ideal_backend_id="reference-density-matrix",
                ideal_baseline_mode=NoiseImpactBaselineMode.IDEAL_NOISE_DISABLED_REPLAY,
                noisy_schedule=NoiseImpactScheduleSummary(
                    program_id=ProgramId("noise-impact:circuit-b"),
                    operation_fingerprint=(),
                    peak_duration_ns=0.0,
                ),
                noisy_idle_decoherence=IdleDecoherenceProfileSnapshot(t1_ns=100.0, t2_ns=200.0),
                ideal_baseline_derivation="test",
            )

    def test_report_json_is_immutable_against_source_and_nested_mutation(self) -> None:
        source_channel = {
            "kind": "binary_readout",
            "p_one_given_zero": 0.1,
            "p_zero_given_one": 0.2,
        }
        report = build_noise_impact_report(
            comparison=NoiseImpactComparisonProvenance(
                circuit_id=ProgramId("noise-impact:immutability"),
                representation="density_matrix",
                noisy_backend_id="reference-density-matrix",
                ideal_backend_id="reference-density-matrix",
                ideal_baseline_mode=NoiseImpactBaselineMode.IDEAL_NOISE_DISABLED_REPLAY,
                noisy_schedule=None,
                noisy_idle_decoherence=None,
                ideal_baseline_derivation="test",
            ),
            ideal_density_matrix=((1.0, 0.0), (0.0, 0.0)),
            noisy_density_matrix=((1.0, 0.0), (0.0, 0.0)),
            qubit_count=1,
            ideal_physical_distribution=(1.0, 0.0),
            noisy_physical_distribution=(1.0, 0.0),
            reported_distribution=(0.9, 0.1),
            readout_channel=source_channel,
        )
        baseline_json = report.to_json()
        source_channel["p_one_given_zero"] = 0.9
        self.assertEqual(report.to_json(), baseline_json)

        readout_finding = next(
            finding
            for finding in report.event_findings
            if finding.kind is NoiseImpactEventKind.READOUT_DISTORTION
        )
        with self.assertRaises(FrozenInstanceError):
            readout_finding.readout.channel.p_one_given_zero = 0.7
        self.assertEqual(report.to_json(), baseline_json)

    def test_build_report_includes_idle_findings_and_deterministic_json(self) -> None:
        circuit = _two_qubit_idle_circuit()
        schedule = schedule_asap(
            circuit,
            {
                IrOperationId("noise-impact:idle-h"): 10.0,
                IrOperationId("noise-impact:idle-x"): 80.0,
            },
        )
        noisy_request = DensityMatrixExecutionRequest(
            schedule=schedule,
            idle_decoherence=IdleDecoherenceProfile(t1_ns=1000.0),
        )

        ideal = simulate_density_matrix(circuit)
        noisy = simulate_density_matrix(circuit, execution=noisy_request)
        report = build_noise_impact_report(
            comparison=NoiseImpactComparisonProvenance(
                circuit_id=circuit.id,
                representation="density_matrix",
                noisy_backend_id="reference-density-matrix",
                ideal_backend_id="reference-density-matrix",
                ideal_baseline_mode=NoiseImpactBaselineMode.IDEAL_NOISE_DISABLED_REPLAY,
                noisy_schedule=None,
                noisy_idle_decoherence=None,
                ideal_baseline_derivation="ideal baseline from noise-disabled exact execution",
            ),
            ideal_density_matrix=ideal.density_matrix,
            noisy_density_matrix=noisy.density_matrix,
            qubit_count=circuit.qubit_count,
            ideal_physical_distribution=None,
            noisy_physical_distribution=None,
            reported_distribution=None,
            idle_events=noisy.idle_decoherence_events,
            gate_events=noisy.gate_noise_events,
            readout_channel=None,
        )

        idle_findings = [
            finding
            for finding in report.event_findings
            if finding.kind is NoiseImpactEventKind.IDLE_DECOHERENCE
        ]
        self.assertGreater(len(idle_findings), 0)
        self.assertEqual(idle_findings[0].provenance, MetricProvenance.OBSERVED)
        self.assertEqual(report.to_json(), report.to_json())

    def test_readout_only_has_zero_state_metrics_and_positive_readout_tvd(self) -> None:
        request = DensityMatrixExecutionRequest(
            ExecutableNoiseModel(readout_channel=BinaryReadoutChannel(0.1, 0.2))
        )
        run = run_logical_module(_return_one.to_logical_module(), execution=request)
        report = build_density_noise_impact_report(run)
        self.assertAlmostEqual(self._metric_value(report, "hilbert_schmidt_distance"), 0.0)
        self.assertAlmostEqual(self._metric_value(report, "physical_output_tvd"), 0.0)
        self.assertGreater(self._metric_value(report, "readout_distortion_tvd"), 0.0)

    def test_pure_dephasing_reduces_coherence_without_population_shift(self) -> None:
        t2 = 600.0
        h_op = Operation(OpCode.H, (0,), IrOperationId("noise-impact:dephase-h"))
        x_op = Operation(OpCode.X, (1,), IrOperationId("noise-impact:dephase-x"))
        circuit = CircuitIR(ProgramId("noise-impact:dephase"), "dephase", 2, (h_op, x_op))
        schedule = schedule_asap(circuit, {h_op.id: 10.0, x_op.id: 120.0})
        request = DensityMatrixExecutionRequest(
            schedule=schedule,
            idle_decoherence=IdleDecoherenceProfile(t2_ns=t2),
        )
        ideal = simulate_density_matrix(circuit)
        noisy = simulate_density_matrix(circuit, execution=request)
        report = build_noise_impact_report(
            comparison=NoiseImpactComparisonProvenance(
                circuit_id=circuit.id,
                representation="density_matrix",
                noisy_backend_id="reference-density-matrix",
                ideal_backend_id="reference-density-matrix",
                ideal_baseline_mode=NoiseImpactBaselineMode.IDEAL_NOISE_DISABLED_REPLAY,
                noisy_schedule=None,
                noisy_idle_decoherence=None,
                ideal_baseline_derivation="test",
            ),
            ideal_density_matrix=ideal.density_matrix,
            noisy_density_matrix=noisy.density_matrix,
            qubit_count=circuit.qubit_count,
            ideal_physical_distribution=None,
            noisy_physical_distribution=None,
            reported_distribution=None,
            idle_events=noisy.idle_decoherence_events,
            gate_events=noisy.gate_noise_events,
        )
        self.assertAlmostEqual(
            self._metric_value(report, "computational_basis_population_tvd"),
            0.0,
            places=10,
        )
        self.assertLess(
            self._metric_value(report, "noisy_l1_coherence"),
            self._metric_value(report, "ideal_l1_coherence"),
        )
        self.assertGreater(self._metric_value(report, "hilbert_schmidt_distance"), 0.0)

    def test_amplitude_damping_shifts_excited_population_toward_ground(self) -> None:
        excite = Operation(OpCode.X, (0,), IrOperationId("noise-impact:amp-x0"))
        delay = Operation(OpCode.X, (1,), IrOperationId("noise-impact:amp-x1"))
        circuit = CircuitIR(ProgramId("noise-impact:amp"), "amp", 2, (excite, delay))
        schedule = schedule_asap(circuit, {excite.id: 10.0, delay.id: 160.0})
        request = DensityMatrixExecutionRequest(
            schedule=schedule,
            idle_decoherence=IdleDecoherenceProfile(t1_ns=200.0),
        )
        ideal = simulate_density_matrix(circuit)
        noisy = simulate_density_matrix(circuit, execution=request)
        report = build_noise_impact_report(
            comparison=NoiseImpactComparisonProvenance(
                circuit_id=circuit.id,
                representation="density_matrix",
                noisy_backend_id="reference-density-matrix",
                ideal_backend_id="reference-density-matrix",
                ideal_baseline_mode=NoiseImpactBaselineMode.IDEAL_NOISE_DISABLED_REPLAY,
                noisy_schedule=None,
                noisy_idle_decoherence=None,
                ideal_baseline_derivation="test",
            ),
            ideal_density_matrix=ideal.density_matrix,
            noisy_density_matrix=noisy.density_matrix,
            qubit_count=circuit.qubit_count,
            ideal_physical_distribution=None,
            noisy_physical_distribution=None,
            reported_distribution=None,
            idle_events=noisy.idle_decoherence_events,
            gate_events=noisy.gate_noise_events,
        )
        ideal_q0_excited = ideal.density_matrix[1][1].real + ideal.density_matrix[3][3].real
        noisy_q0_excited = noisy.density_matrix[1][1].real + noisy.density_matrix[3][3].real
        self.assertLess(noisy_q0_excited, ideal_q0_excited)
        self.assertGreater(self._metric_value(report, "computational_basis_population_tvd"), 0.0)

    def test_combined_gate_idle_readout_has_all_event_kinds(self) -> None:
        request = self._scheduled_idle_request_for_module()
        request = DensityMatrixExecutionRequest(
            noise_model=ExecutableNoiseModel(
                gate_channels=(
                    GateChannelBinding(OneQubitGate.H, AmplitudeDampingChannel(0.2)),
                ),
                readout_channel=BinaryReadoutChannel(0.05, 0.1),
            ),
            schedule=request.schedule,
            idle_decoherence=request.idle_decoherence,
        )
        run = run_logical_module(_idle_sensitive_classical.to_logical_module(), execution=request)
        report = build_density_noise_impact_report(run)
        finding_kinds = {finding.kind for finding in report.event_findings}
        self.assertIn(NoiseImpactEventKind.GATE_CHANNEL, finding_kinds)
        self.assertIn(NoiseImpactEventKind.IDLE_DECOHERENCE, finding_kinds)
        self.assertIn(NoiseImpactEventKind.READOUT_DISTORTION, finding_kinds)


if __name__ == "__main__":
    unittest.main()
