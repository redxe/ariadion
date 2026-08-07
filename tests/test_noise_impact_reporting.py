from __future__ import annotations

import unittest

from ariadion import Bit, Qubit, quantum, x
from ariadion_core import IrOperationId, ProgramId
from ariadion_ir import CircuitIR, OpCode, Operation
from ariadion_noise import (
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
    MetricProvenance,
    NoiseImpactComparisonProvenance,
    NoiseImpactEventKind,
    build_noise_impact_report,
)

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
    def test_runtime_helper_reports_zero_deltas_without_noise(self) -> None:
        run = run_logical_module(
            _return_one.to_logical_module(),
            execution=DensityMatrixExecutionRequest(),
        )
        self.assertTrue(hasattr(run, "simulation"))

        report = build_density_noise_impact_report(
            run,
            execution=DensityMatrixExecutionRequest(),
        )
        metric_by_name = {metric.name: metric.value for metric in report.metrics}
        self.assertAlmostEqual(metric_by_name["hilbert_schmidt_distance"], 0.0)
        self.assertAlmostEqual(metric_by_name["physical_output_tvd"], 0.0)
        self.assertAlmostEqual(metric_by_name["readout_distortion_tvd"], 0.0)
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
        report = build_density_noise_impact_report(
            run,
            execution=request,
            backend_id="reference-density-matrix",
        )

        metric_by_name = {metric.name: metric.value for metric in report.metrics}
        self.assertGreater(metric_by_name["physical_output_tvd"], 0.0)
        self.assertGreater(metric_by_name["readout_distortion_tvd"], 0.0)

        finding_kinds = tuple(finding.kind for finding in report.event_findings)
        self.assertIn(NoiseImpactEventKind.GATE_CHANNEL, finding_kinds)
        self.assertIn(NoiseImpactEventKind.READOUT_DISTORTION, finding_kinds)

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
                backend_id="reference-density-matrix",
                ideal_baseline_derivation="ideal baseline from noise-disabled exact execution",
            ),
            ideal_density_matrix=ideal.density_matrix,
            noisy_density_matrix=noisy.density_matrix,
            qubit_count=circuit.qubit_count,
            ideal_physical_distribution=(),
            noisy_physical_distribution=(),
            reported_distribution=(),
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


if __name__ == "__main__":
    unittest.main()
