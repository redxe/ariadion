from __future__ import annotations

from dataclasses import replace
import json
from math import inf, nan
import unittest

from ariadion import Bit, Qubit, cx, h, observe, quantum, x
from ariadion_core import ProgramId
from ariadion_noise import (
    BinaryReadoutChannel,
    ExecutableNoiseModel,
    GateChannelBinding,
    NoiseFeature,
    OneQubitGate,
)
from ariadion_runtime import (
    DensityExecutionCoverageIssue,
    DensityExecutionCoverageSnapshot,
    DensityExecutionProvenanceSnapshot,
    DensityMatrixExecutionRequest,
    build_bare_reliability_report,
    run_logical_module,
)
from ariadion_semantics import ClassicalAcceptanceCriterion, ReliabilityGoal
from theonoe import (
    BareReliabilityBitOrder,
    BareReliabilityCompletenessIssue,
    BareReliabilityDistributionKind,
    BareReliabilityGoalVerdict,
    BareReliabilityProbabilityScope,
    BareReliabilityStatus,
    BoundClassicalAcceptanceCriterion,
    BareReliabilityReport,
)


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


@quantum
def _hybrid_return() -> tuple[Bit, Qubit]:
    observed = Qubit()
    returned = Qubit()
    h(observed)
    h(returned)
    result = observe(observed)
    return result, returned


class BareReliabilitySemanticsTests(unittest.TestCase):
    def test_bound_snapshot_index_mapping_and_enum_projection(self) -> None:
        snapshot = BoundClassicalAcceptanceCriterion(
            circuit_id=ProgramId("bare-reliability:index-map"),
            result_ids=("r0", "r1", "r2"),
            distribution_kind=BareReliabilityDistributionKind.REPORTED_OUTPUT,
            accepted_outcomes=((1, 0, 1), (0, 1, 0)),
        )

        self.assertEqual(snapshot.accepted_indices, (2, 5))
        self.assertEqual(snapshot.bit_order, BareReliabilityBitOrder.TARGETS_LSB_FIRST)
        self.assertEqual(snapshot.scope, BareReliabilityProbabilityScope.JOINT_RETURN)
        self.assertEqual(snapshot.distribution_kind, BareReliabilityDistributionKind.REPORTED_OUTPUT)
        payload = snapshot.to_dict()
        payload["accepted_outcomes"][0][0] = 0
        self.assertEqual(snapshot.accepted_outcomes, ((0, 1, 0), (1, 0, 1)))

    def test_bound_snapshot_rejects_duplicate_or_invalid_outcomes(self) -> None:
        with self.assertRaisesRegex(ValueError, "non-empty tuple"):
            BoundClassicalAcceptanceCriterion(
                circuit_id=ProgramId("bare-reliability:bad"),
                result_ids=(),
            )
        with self.assertRaisesRegex(ValueError, "unique"):
            BoundClassicalAcceptanceCriterion(
                circuit_id=ProgramId("bare-reliability:bad"),
                result_ids=("r0",),
                accepted_outcomes=((1,), (1,)),
            )
        with self.assertRaisesRegex(ValueError, "match result_ids"):
            BoundClassicalAcceptanceCriterion(
                circuit_id=ProgramId("bare-reliability:bad"),
                result_ids=("r0", "r1"),
                accepted_outcomes=((1,),),
            )


class BareReliabilityRuntimeTests(unittest.TestCase):
    def _goal(self, failure_probability: float, confidence: float | None = None) -> ReliabilityGoal:
        return ReliabilityGoal(failure_probability, confidence=confidence)

    def _classical_one_run(self):
        return run_logical_module(_deterministic_classical_one.to_logical_module(), execution=DensityMatrixExecutionRequest())

    def _classical_two_run(self):
        return run_logical_module(_deterministic_classical_two.to_logical_module(), execution=DensityMatrixExecutionRequest())

    def _hybrid_run(self):
        return run_logical_module(_hybrid_return.to_logical_module(), execution=DensityMatrixExecutionRequest())

    def test_supported_report_uses_exact_model_relative_failure_mass(self) -> None:
        run = self._classical_one_run()
        report = build_bare_reliability_report(
            run,
            goal=self._goal(0.1),
            acceptance=ClassicalAcceptanceCriterion(1, ((1,),)),
            distribution_kind=BareReliabilityDistributionKind.PHYSICAL_OUTPUT,
        )

        self.assertEqual(report.status, BareReliabilityStatus.SUPPORTED)
        self.assertEqual(report.goal_verdict, BareReliabilityGoalVerdict.SATISFIED)
        self.assertAlmostEqual(report.model_relative_success_probability, 1.0)
        self.assertAlmostEqual(report.model_relative_failure_probability, 0.0)
        self.assertAlmostEqual(report.goal_margin, 0.1)
        self.assertEqual(report.bound_acceptance.bit_order, BareReliabilityBitOrder.TARGETS_LSB_FIRST)
        self.assertEqual(report.bound_acceptance.scope, BareReliabilityProbabilityScope.JOINT_RETURN)
        self.assertEqual(report.bound_acceptance.circuit_id, run.compilation.ir.id)
        self.assertEqual(report.executed_noise_features, ())
        self.assertEqual(report.unsupported_features, ())
        self.assertEqual(report.completeness_issues, ())

    def test_report_selects_physical_or_reported_distribution(self) -> None:
        request = DensityMatrixExecutionRequest(
            noise_model=ExecutableNoiseModel(
                readout_channel=BinaryReadoutChannel(0.0, 0.2),
            )
        )
        run = run_logical_module(_deterministic_classical_one.to_logical_module(), execution=request)
        physical = build_bare_reliability_report(
            run,
            goal=self._goal(0.1),
            acceptance=ClassicalAcceptanceCriterion(1, ((1,),)),
            distribution_kind=BareReliabilityDistributionKind.PHYSICAL_OUTPUT,
        )
        reported = build_bare_reliability_report(
            run,
            goal=self._goal(0.1),
            acceptance=ClassicalAcceptanceCriterion(1, ((1,),)),
            distribution_kind=BareReliabilityDistributionKind.REPORTED_OUTPUT,
        )

        self.assertAlmostEqual(physical.model_relative_failure_probability, 0.0)
        self.assertAlmostEqual(reported.model_relative_failure_probability, 0.2)
        self.assertEqual(physical.bound_acceptance.distribution_kind, BareReliabilityDistributionKind.PHYSICAL_OUTPUT)
        self.assertEqual(reported.bound_acceptance.distribution_kind, BareReliabilityDistributionKind.REPORTED_OUTPUT)

    def test_empty_and_full_acceptance_are_supported(self) -> None:
        run = self._classical_one_run()
        empty = build_bare_reliability_report(
            run,
            goal=self._goal(1.0),
            acceptance=ClassicalAcceptanceCriterion(1, ()),
            distribution_kind=BareReliabilityDistributionKind.PHYSICAL_OUTPUT,
        )
        full = build_bare_reliability_report(
            run,
            goal=self._goal(0.1),
            acceptance=ClassicalAcceptanceCriterion(1, ((0,), (1,))),
            distribution_kind=BareReliabilityDistributionKind.PHYSICAL_OUTPUT,
        )

        self.assertAlmostEqual(empty.model_relative_failure_probability, 1.0)
        self.assertAlmostEqual(full.model_relative_failure_probability, 0.0)

    def test_tolerance_band_is_not_evaluated(self) -> None:
        run = self._balanced_classical_one_run()
        report = build_bare_reliability_report(
            run,
            goal=self._goal(0.5),
            acceptance=ClassicalAcceptanceCriterion(1, ((1,),)),
            distribution_kind=BareReliabilityDistributionKind.PHYSICAL_OUTPUT,
        )

        self.assertEqual(report.status, BareReliabilityStatus.SUPPORTED)
        self.assertEqual(report.goal_verdict, BareReliabilityGoalVerdict.NOT_EVALUATED)
        self.assertIsNone(report.goal_margin)
        self.assertTrue(report.status_reasons)

    def _balanced_classical_one_run(self):
        return run_logical_module(_balanced_classical_one.to_logical_module(), execution=DensityMatrixExecutionRequest())

    def test_confidence_goal_is_indeterminate(self) -> None:
        run = self._classical_one_run()
        report = build_bare_reliability_report(
            run,
            goal=self._goal(0.1, confidence=0.95),
            acceptance=ClassicalAcceptanceCriterion(1, ((1,),)),
            distribution_kind=BareReliabilityDistributionKind.PHYSICAL_OUTPUT,
        )

        self.assertEqual(report.status, BareReliabilityStatus.INDETERMINATE)
        self.assertEqual(report.goal_verdict, BareReliabilityGoalVerdict.NOT_EVALUATED)
        self.assertIsNone(report.goal_margin)

    def test_cx_forces_incomplete_model_and_missing_issue_is_rejected(self) -> None:
        run = self._classical_two_run()
        report = build_bare_reliability_report(
            run,
            goal=self._goal(0.1),
            acceptance=ClassicalAcceptanceCriterion(2, ((0, 0),)),
            distribution_kind=BareReliabilityDistributionKind.PHYSICAL_OUTPUT,
        )

        self.assertEqual(report.status, BareReliabilityStatus.INCOMPLETE_MODEL)
        self.assertIn(
            BareReliabilityCompletenessIssue.IDEAL_ONLY_TWO_QUBIT_OPERATION_PRESENT,
            report.completeness_issues,
        )
        self.assertEqual(report.goal_verdict, BareReliabilityGoalVerdict.NOT_EVALUATED)
        with self.assertRaisesRegex(ValueError, "retain required circuit issues"):
            replace(
                run,
                provenance=replace(
                    run.provenance,
                    coverage=DensityExecutionCoverageSnapshot(
                        executed_noise_features=run.provenance.coverage.executed_noise_features,
                        unsupported_features=run.provenance.coverage.unsupported_features,
                        assumptions=run.provenance.coverage.assumptions,
                        completeness_issues=(),
                    ),
                ),
            )

    def test_absent_coverage_and_unsupported_features_are_incomplete(self) -> None:
        run = self._classical_one_run()
        without_coverage = replace(
            run,
            provenance=replace(run.provenance, coverage=None),
        )
        with_unsupported = replace(
            run,
            provenance=replace(
                run.provenance,
                coverage=DensityExecutionCoverageSnapshot(
                    executed_noise_features=run.provenance.coverage.executed_noise_features,
                    unsupported_features=(NoiseFeature.LEAKAGE,),
                    assumptions=run.provenance.coverage.assumptions,
                    completeness_issues=(),
                ),
            ),
        )

        absent_report = build_bare_reliability_report(
            without_coverage,
            goal=self._goal(0.1),
            acceptance=ClassicalAcceptanceCriterion(1, ((1,),)),
            distribution_kind=BareReliabilityDistributionKind.PHYSICAL_OUTPUT,
        )
        unsupported_report = build_bare_reliability_report(
            with_unsupported,
            goal=self._goal(0.1),
            acceptance=ClassicalAcceptanceCriterion(1, ((1,),)),
            distribution_kind=BareReliabilityDistributionKind.PHYSICAL_OUTPUT,
        )

        self.assertEqual(absent_report.status, BareReliabilityStatus.INCOMPLETE_MODEL)
        self.assertEqual(unsupported_report.status, BareReliabilityStatus.INCOMPLETE_MODEL)
        self.assertTrue(unsupported_report.unsupported_features)

    def test_quantum_only_and_hybrid_runs_are_unsupported(self) -> None:
        quantum_only = run_logical_module(_quantum_only_return.to_logical_module(), execution=DensityMatrixExecutionRequest())
        hybrid = self._hybrid_run()

        quantum_only_report = build_bare_reliability_report(
            quantum_only,
            goal=self._goal(0.1),
            acceptance=ClassicalAcceptanceCriterion(1, ((1,),)),
            distribution_kind=BareReliabilityDistributionKind.PHYSICAL_OUTPUT,
        )
        hybrid_report = build_bare_reliability_report(
            hybrid,
            goal=self._goal(0.1),
            acceptance=ClassicalAcceptanceCriterion(1, ((1,),)),
            distribution_kind=BareReliabilityDistributionKind.PHYSICAL_OUTPUT,
        )

        self.assertEqual(quantum_only_report.status, BareReliabilityStatus.UNSUPPORTED)
        self.assertEqual(hybrid_report.status, BareReliabilityStatus.UNSUPPORTED)
        self.assertIsNone(quantum_only_report.bound_acceptance)
        self.assertIsNone(hybrid_report.bound_acceptance)

    def test_wrong_run_type_and_criterion_mismatch_raise(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires DensityMatrixLogicalRunResult"):
            build_bare_reliability_report(
                run_logical_module(_deterministic_classical_one.to_logical_module()),
                goal=self._goal(0.1),
                acceptance=ClassicalAcceptanceCriterion(1, ((1,),)),
                distribution_kind=BareReliabilityDistributionKind.PHYSICAL_OUTPUT,
            )
        with self.assertRaisesRegex(ValueError, "arity must match"):
            build_bare_reliability_report(
                self._classical_one_run(),
                goal=self._goal(0.1),
                acceptance=ClassicalAcceptanceCriterion(2, ((1, 1),)),
                distribution_kind=BareReliabilityDistributionKind.PHYSICAL_OUTPUT,
            )

    def test_report_serialization_is_canonical_and_isolated(self) -> None:
        run = self._classical_one_run()
        report = build_bare_reliability_report(
            run,
            goal=self._goal(0.1),
            acceptance=ClassicalAcceptanceCriterion(1, ((1,),)),
            distribution_kind=BareReliabilityDistributionKind.PHYSICAL_OUTPUT,
        )
        payload = report.to_dict()
        payload["goal"]["maximum_failure_probability"] = 0.9
        payload["bound_acceptance"]["accepted_outcomes"][0][0] = 0
        payload["supporting_noise_impact"]["limitations"][0] = "mutated"

        self.assertEqual(report.goal.maximum_failure_probability, 0.1)
        self.assertEqual(report.bound_acceptance.accepted_outcomes, ((1,),))
        self.assertEqual(json.loads(report.to_json()), report.to_dict())

    def test_constructor_rejects_unpaired_scalar_diagnostics(self) -> None:
        report = build_bare_reliability_report(
            self._classical_one_run(),
            goal=self._goal(0.1),
            acceptance=ClassicalAcceptanceCriterion(1, ((1,),)),
            distribution_kind=BareReliabilityDistributionKind.PHYSICAL_OUTPUT,
        )

        with self.assertRaisesRegex(ValueError, "require both success and failure"):
            replace(report, model_relative_failure_probability=None)
        with self.assertRaisesRegex(ValueError, "require both success and failure"):
            replace(report, model_relative_success_probability=None)

    def test_constructor_rejects_invalid_scalar_diagnostics(self) -> None:
        report = build_bare_reliability_report(
            self._classical_one_run(),
            goal=self._goal(0.1),
            acceptance=ClassicalAcceptanceCriterion(1, ((1,),)),
            distribution_kind=BareReliabilityDistributionKind.PHYSICAL_OUTPUT,
        )

        with self.assertRaisesRegex(ValueError, "must be numeric"):
            replace(report, model_relative_success_probability=True)
        with self.assertRaisesRegex(ValueError, "must be finite"):
            replace(report, model_relative_success_probability=nan)
        with self.assertRaisesRegex(ValueError, "must be finite"):
            replace(report, model_relative_success_probability=inf)
        with self.assertRaisesRegex(ValueError, "must be finite"):
            replace(report, model_relative_success_probability=-inf)
        with self.assertRaisesRegex(ValueError, "within \[0, 1\]"):
            replace(report, model_relative_success_probability=-0.1)
        with self.assertRaisesRegex(ValueError, "within \[0, 1\]"):
            replace(report, model_relative_success_probability=1.1)
        with self.assertRaisesRegex(ValueError, "sum to one"):
            replace(
                report,
                model_relative_success_probability=0.6,
                model_relative_failure_probability=0.6,
            )

    def test_constructor_rejects_mismatched_supporting_noise_impact_circuit(self) -> None:
        report = build_bare_reliability_report(
            self._classical_one_run(),
            goal=self._goal(0.1),
            acceptance=ClassicalAcceptanceCriterion(1, ((1,),)),
            distribution_kind=BareReliabilityDistributionKind.PHYSICAL_OUTPUT,
        )
        forged_support = replace(
            report.supporting_noise_impact,
            comparison=replace(
                report.supporting_noise_impact.comparison,
                circuit_id=ProgramId("bare-reliability:forged-circuit"),
            ),
        )

        with self.assertRaisesRegex(ValueError, "must match supporting noise impact circuit_id"):
            replace(report, supporting_noise_impact=forged_support)

    def test_valid_supported_report_remains_constructible_and_serialization_stable(self) -> None:
        report = build_bare_reliability_report(
            self._classical_one_run(),
            goal=self._goal(0.1),
            acceptance=ClassicalAcceptanceCriterion(1, ((1,),)),
            distribution_kind=BareReliabilityDistributionKind.PHYSICAL_OUTPUT,
        )
        reconstructed = BareReliabilityReport(
            schema_version=report.schema_version,
            method=report.method,
            status=report.status,
            goal_verdict=report.goal_verdict,
            goal=report.goal,
            bound_acceptance=report.bound_acceptance,
            model_relative_success_probability=report.model_relative_success_probability,
            model_relative_failure_probability=report.model_relative_failure_probability,
            goal_margin=report.goal_margin,
            supporting_noise_impact=report.supporting_noise_impact,
            executed_noise_features=report.executed_noise_features,
            unsupported_features=report.unsupported_features,
            assumptions=report.assumptions,
            completeness_issues=report.completeness_issues,
            limitations=report.limitations,
            status_reasons=report.status_reasons,
        )

        self.assertEqual(reconstructed, report)
        self.assertEqual(reconstructed.to_dict(), report.to_dict())
        self.assertEqual(reconstructed.to_json(), report.to_json())

    def test_distribution_absent_provenance_rejects_non_snapshot_coverage(self) -> None:
        quantum_only = run_logical_module(
            _quantum_only_return.to_logical_module(),
            execution=DensityMatrixExecutionRequest(),
        )

        with self.assertRaisesRegex(ValueError, "coverage must be DensityExecutionCoverageSnapshot or None"):
            replace(
                quantum_only,
                provenance=replace(quantum_only.provenance, coverage=object()),
            )

        valid_coverage = DensityExecutionCoverageSnapshot(
            executed_noise_features=quantum_only.provenance.coverage.executed_noise_features,
            unsupported_features=quantum_only.provenance.coverage.unsupported_features,
            assumptions=quantum_only.provenance.coverage.assumptions,
            completeness_issues=quantum_only.provenance.coverage.completeness_issues,
        )
        reconstructed = replace(
            quantum_only,
            provenance=replace(quantum_only.provenance, coverage=valid_coverage),
        )

        self.assertIsInstance(reconstructed.provenance, DensityExecutionProvenanceSnapshot)
        self.assertEqual(reconstructed.provenance.coverage, valid_coverage)

    def test_manual_bound_snapshot_and_runtime_enum_mapping_are_theonoe_owned(self) -> None:
        run = self._classical_one_run()
        report = build_bare_reliability_report(
            run,
            goal=self._goal(0.1),
            acceptance=ClassicalAcceptanceCriterion(1, ((1,),)),
            distribution_kind=BareReliabilityDistributionKind.REPORTED_OUTPUT,
        )

        self.assertIsInstance(report.bound_acceptance.bit_order, BareReliabilityBitOrder)
        self.assertIsInstance(report.bound_acceptance.scope, BareReliabilityProbabilityScope)
        self.assertEqual(report.bound_acceptance.distribution_kind, BareReliabilityDistributionKind.REPORTED_OUTPUT)
