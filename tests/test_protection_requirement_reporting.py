from __future__ import annotations

from dataclasses import replace
import json
import unittest

from ariadion import Bit, Qubit, cx, h, quantum, x
from ariadion_noise import BinaryReadoutChannel, ExecutableNoiseModel
from ariadion_runtime import (
    DensityMatrixExecutionRequest,
    build_bare_reliability_report,
    run_logical_module,
)
from ariadion_semantics import ClassicalAcceptanceCriterion, ReliabilityGoal
import theonoe
from theonoe import (
    BARE_RELIABILITY_ABS_TOLERANCE,
    BareReliabilityDistributionKind,
    BareReliabilityStatus,
    SeparabilityReport,
    StateReport,
    StateTransition,
    ProtectionNeedVerdict,
    ProtectionRequirementMetrics,
    ProtectionRequirementReport,
    build_protection_requirement_report,
)

try:
    from ariadion_simulator_numpy import NumpyDensityMatrixBackend

    HAS_NUMPY_SIMULATOR = True
except ModuleNotFoundError:  # pragma: no cover - exercised in dependency-minimal CI
    NumpyDensityMatrixBackend = None  # type: ignore[assignment]
    HAS_NUMPY_SIMULATOR = False


@quantum
def _deterministic_classical_one() -> Bit:
    q = Qubit()
    x(q)
    return q


@quantum
def _balanced_classical_one() -> Bit:
    q = Qubit()
    h(q)
    return q


@quantum
def _deterministic_classical_two() -> tuple[Bit, Bit]:
    left = Qubit()
    right = Qubit()
    h(left)
    cx(left, right)
    return left, right


@quantum
def _quantum_only_return() -> Qubit:
    q = Qubit()
    h(q)
    return q


class ProtectionRequirementReportingTests(unittest.TestCase):
    def _goal(self, failure_probability: float, confidence: float | None = None) -> ReliabilityGoal:
        return ReliabilityGoal(failure_probability, confidence=confidence)

    def _supported_satisfied_report(self):
        run = run_logical_module(
            _deterministic_classical_one.to_logical_module(),
            execution=DensityMatrixExecutionRequest(),
        )
        return build_bare_reliability_report(
            run,
            goal=self._goal(0.1),
            acceptance=ClassicalAcceptanceCriterion(1, ((1,),)),
            distribution_kind=BareReliabilityDistributionKind.PHYSICAL_OUTPUT,
        )

    def _supported_not_evaluated_report(self):
        run = run_logical_module(
            _balanced_classical_one.to_logical_module(),
            execution=DensityMatrixExecutionRequest(),
        )
        bare = build_bare_reliability_report(
            run,
            goal=self._goal(0.5),
            acceptance=ClassicalAcceptanceCriterion(1, ((1,),)),
            distribution_kind=BareReliabilityDistributionKind.PHYSICAL_OUTPUT,
        )
        return replace(
            bare,
            model_relative_failure_probability=0.5 + BARE_RELIABILITY_ABS_TOLERANCE / 2,
        )

    def _supported_violated_report(self):
        request = DensityMatrixExecutionRequest(
            noise_model=ExecutableNoiseModel(
                readout_channel=BinaryReadoutChannel(0.0, 0.2),
            )
        )
        run = run_logical_module(
            _deterministic_classical_one.to_logical_module(),
            execution=request,
        )
        return build_bare_reliability_report(
            run,
            goal=self._goal(0.1),
            acceptance=ClassicalAcceptanceCriterion(1, ((1,),)),
            distribution_kind=BareReliabilityDistributionKind.REPORTED_OUTPUT,
        )

    def _incomplete_report(self):
        run = run_logical_module(
            _deterministic_classical_two.to_logical_module(),
            execution=DensityMatrixExecutionRequest(),
        )
        return build_bare_reliability_report(
            run,
            goal=self._goal(0.1),
            acceptance=ClassicalAcceptanceCriterion(2, ((0, 0),)),
            distribution_kind=BareReliabilityDistributionKind.PHYSICAL_OUTPUT,
        )

    def _indeterminate_report(self):
        run = run_logical_module(
            _deterministic_classical_one.to_logical_module(),
            execution=DensityMatrixExecutionRequest(),
        )
        return build_bare_reliability_report(
            run,
            goal=self._goal(0.1, confidence=0.95),
            acceptance=ClassicalAcceptanceCriterion(1, ((1,),)),
            distribution_kind=BareReliabilityDistributionKind.PHYSICAL_OUTPUT,
        )

    def _unsupported_report(self):
        run = run_logical_module(
            _quantum_only_return.to_logical_module(),
            execution=DensityMatrixExecutionRequest(),
        )
        return build_bare_reliability_report(
            run,
            goal=self._goal(0.1),
            acceptance=ClassicalAcceptanceCriterion(1, ((1,),)),
            distribution_kind=BareReliabilityDistributionKind.PHYSICAL_OUTPUT,
        )

    def test_supported_satisfied_maps_to_no_protection_required(self) -> None:
        bare = self._supported_satisfied_report()
        report = build_protection_requirement_report(bare)

        self.assertEqual(report.status, BareReliabilityStatus.SUPPORTED)
        self.assertEqual(report.need_verdict, ProtectionNeedVerdict.NO_PROTECTION_REQUIRED)
        self.assertIsNotNone(report.metrics)
        assert report.metrics is not None
        self.assertEqual(report.metrics.required_failure_reduction, 0.0)
        self.assertIsNone(report.metrics.required_failure_suppression)
        self.assertLess(report.metrics.signed_failure_excess, 0.0)
        self.assertLess(report.metrics.relative_failure_excess, 0.0)

    def test_supported_not_evaluated_maps_to_no_protection_required_with_positive_excess(self) -> None:
        bare = self._supported_not_evaluated_report()
        report = build_protection_requirement_report(bare)

        self.assertEqual(report.status, BareReliabilityStatus.SUPPORTED)
        self.assertEqual(report.need_verdict, ProtectionNeedVerdict.NO_PROTECTION_REQUIRED)
        self.assertIsNotNone(report.metrics)
        assert report.metrics is not None
        self.assertEqual(report.metrics.required_failure_reduction, 0.0)
        self.assertIsNone(report.metrics.required_failure_suppression)
        self.assertGreater(report.metrics.signed_failure_excess, 0.0)
        self.assertGreater(report.metrics.relative_failure_excess, 0.0)

    def test_supported_violated_maps_to_protection_required(self) -> None:
        bare = self._supported_violated_report()
        report = build_protection_requirement_report(bare)

        self.assertEqual(report.status, BareReliabilityStatus.SUPPORTED)
        self.assertEqual(report.need_verdict, ProtectionNeedVerdict.PROTECTION_REQUIRED)
        self.assertIsNotNone(report.metrics)
        assert report.metrics is not None
        self.assertGreater(report.metrics.required_failure_reduction, 0.0)
        self.assertGreater(report.metrics.required_failure_suppression, 1.0)
        self.assertGreater(report.metrics.signed_failure_excess, 0.0)
        self.assertGreater(report.metrics.relative_failure_excess, 0.0)

    def test_non_supported_reports_map_to_not_assessed_without_metrics(self) -> None:
        for bare in (self._incomplete_report(), self._indeterminate_report(), self._unsupported_report()):
            with self.subTest(status=bare.status):
                report = build_protection_requirement_report(bare)
                self.assertEqual(report.need_verdict, ProtectionNeedVerdict.NOT_ASSESSED)
                self.assertIsNone(report.metrics)

    def test_zero_goal_remains_rejected_by_reliability_goal(self) -> None:
        with self.assertRaisesRegex(ValueError, "maximum failure probability"):
            ReliabilityGoal(0)

    def test_public_export_surface_retains_existing_inspection_reports(self) -> None:
        for name, symbol in (
            ("SeparabilityReport", SeparabilityReport),
            ("StateReport", StateReport),
            ("StateTransition", StateTransition),
        ):
            with self.subTest(name=name):
                self.assertIn(name, theonoe.__all__)
                self.assertIs(getattr(theonoe, name), symbol)

    def test_constructor_rejects_wrong_schema_version(self) -> None:
        report = build_protection_requirement_report(self._supported_satisfied_report())
        with self.assertRaisesRegex(ValueError, "schema_version"):
            replace(report, schema_version=report.schema_version + 1)

    def test_constructor_rejects_non_bare_supporting_evidence(self) -> None:
        report = build_protection_requirement_report(self._supported_satisfied_report())
        with self.assertRaisesRegex(ValueError, "BareReliabilityReport"):
            replace(report, supporting_bare_reliability=object())  # type: ignore[arg-type]

    def test_incomplete_model_rejects_metrics(self) -> None:
        report = build_protection_requirement_report(self._incomplete_report())
        with self.assertRaisesRegex(ValueError, "cannot carry metrics"):
            replace(
                report,
                metrics=ProtectionRequirementMetrics(0.0, 0.0, 0.0, None),
            )

    def test_indeterminate_rejects_metrics(self) -> None:
        report = build_protection_requirement_report(self._indeterminate_report())
        with self.assertRaisesRegex(ValueError, "cannot carry metrics"):
            replace(
                report,
                metrics=ProtectionRequirementMetrics(0.0, 0.0, 0.0, None),
            )

    def test_constructor_rejects_contradictory_status_need_and_metrics(self) -> None:
        report = build_protection_requirement_report(self._supported_satisfied_report())
        with self.assertRaisesRegex(ValueError, "must match supporting bare reliability status"):
            replace(
                report,
                supporting_bare_reliability=self._unsupported_report(),
            )
        with self.assertRaisesRegex(ValueError, "need_verdict"):
            replace(report, need_verdict=ProtectionNeedVerdict.PROTECTION_REQUIRED)
        with self.assertRaisesRegex(ValueError, "require metrics"):
            replace(report, metrics=None)
        unsupported_report = build_protection_requirement_report(self._unsupported_report())
        with self.assertRaisesRegex(ValueError, "cannot carry metrics"):
            replace(
                unsupported_report,
                metrics=ProtectionRequirementMetrics(0.0, 0.0, 0.0, None),
            )

    def test_metrics_reject_forged_and_non_numeric_values(self) -> None:
        with self.assertRaisesRegex(ValueError, "numeric"):
            ProtectionRequirementMetrics(True, 0.0, 0.0, None)
        with self.assertRaisesRegex(ValueError, "finite"):
            ProtectionRequirementMetrics(float("nan"), 0.0, 0.0, None)
        with self.assertRaisesRegex(ValueError, "finite"):
            ProtectionRequirementMetrics(float("inf"), 0.0, 0.0, None)
        with self.assertRaisesRegex(ValueError, "positive"):
            ProtectionRequirementMetrics(0.0, 0.0, 0.0, 0.0)

        report = build_protection_requirement_report(self._supported_satisfied_report())
        with self.assertRaisesRegex(ValueError, "must match nested bare reliability evidence"):
            replace(
                report,
                metrics=ProtectionRequirementMetrics(
                    signed_failure_excess=0.0,
                    required_failure_reduction=0.0,
                    relative_failure_excess=0.0,
                    required_failure_suppression=None,
                ),
            )

    def test_supported_report_reconstructs_and_serializes_isolated(self) -> None:
        report = build_protection_requirement_report(self._supported_satisfied_report())
        reconstructed = ProtectionRequirementReport(
            schema_version=report.schema_version,
            status=report.status,
            need_verdict=report.need_verdict,
            metrics=report.metrics,
            supporting_bare_reliability=report.supporting_bare_reliability,
            assumptions=report.assumptions,
            limitations=report.limitations,
            status_reasons=report.status_reasons,
        )
        self.assertEqual(reconstructed, report)
        payload = report.to_dict()
        payload["metrics"]["required_failure_reduction"] = 99.0
        payload["supporting_bare_reliability"]["goal"]["maximum_failure_probability"] = 0.9
        self.assertEqual(json.loads(report.to_json()), report.to_dict())
        self.assertEqual(reconstructed.to_dict(), report.to_dict())

    def test_canonical_json_stability(self) -> None:
        report = build_protection_requirement_report(self._supported_violated_report())
        self.assertEqual(report.to_json(), report.to_json())
        payload = json.loads(report.to_json())
        self.assertEqual(payload["need_verdict"], ProtectionNeedVerdict.PROTECTION_REQUIRED.value)

    @unittest.skipUnless(HAS_NUMPY_SIMULATOR, "requires optional NumPy simulator backend")
    def test_semantically_equal_supporting_evidence_produces_identical_report(self) -> None:
        assert NumpyDensityMatrixBackend is not None
        reference_run = run_logical_module(
            _deterministic_classical_one.to_logical_module(),
            execution=DensityMatrixExecutionRequest(),
        )
        numpy_run = run_logical_module(
            _deterministic_classical_one.to_logical_module(),
            execution=DensityMatrixExecutionRequest(),
        )
        reference_bare = build_bare_reliability_report(
            reference_run,
            goal=self._goal(0.1),
            acceptance=ClassicalAcceptanceCriterion(1, ((1,),)),
            distribution_kind=BareReliabilityDistributionKind.PHYSICAL_OUTPUT,
        )
        numpy_bare = build_bare_reliability_report(
            numpy_run,
            goal=self._goal(0.1),
            acceptance=ClassicalAcceptanceCriterion(1, ((1,),)),
            distribution_kind=BareReliabilityDistributionKind.PHYSICAL_OUTPUT,
        )
        reference_report = build_protection_requirement_report(reference_bare)
        numpy_report = build_protection_requirement_report(numpy_bare)
        self.assertEqual(reference_report.to_dict(), numpy_report.to_dict())


if __name__ == "__main__":
    unittest.main()
