from __future__ import annotations

import unittest

from ariadion import Qubit, cx, h, quantum
from daidalon import (
    LogicalLifetimeEndReason,
    LogicalValueOwnership,
    QuantumReleaseKind,
    analyze_logical_lifetimes,
    analyze_quantum_releases,
    compile_logical_module,
    expand_logical_module,
)


@quantum
def _creation_order() -> None:
    first = Qubit()
    second = Qubit()
    h(first)
    h(second)


@quantum
def _root_local_last_use() -> None:
    temporary = Qubit()
    h(temporary)


@quantum
def _borrowed_and_local(input_value: Qubit) -> None:
    temporary = Qubit()
    h(temporary)
    h(input_value)


@quantum
def _entangled_temporary(value: Qubit) -> None:
    temporary = Qubit()
    h(temporary)
    cx(temporary, value)


@quantum
def _entangled_temporary_root() -> Qubit:
    output = Qubit()
    _entangled_temporary(output)
    return output


@quantum
def _returned_local() -> Qubit:
    value = Qubit()
    h(value)
    return value


@quantum
def _burn() -> None:
    temporary = Qubit()
    h(temporary)


@quantum
def _burn_twice() -> None:
    _burn()
    _burn()


class QuantumReleaseAnalysisTests(unittest.TestCase):
    def test_lifetimes_begin_when_local_declarations_are_instantiated(self) -> None:
        expanded = expand_logical_module(_creation_order.to_logical_module())
        analysis = analyze_logical_lifetimes(expanded)

        self.assertEqual(
            tuple(qubit.creation_instruction_index for qubit in expanded.qubits),
            (0, 0),
        )
        self.assertEqual(
            tuple(lifetime.first_instruction_index for lifetime in analysis.lifetimes),
            (0, 0),
        )
        self.assertEqual(analysis.peak_semantically_live_values, 2)
        self.assertEqual(analysis.peak_live_logical_values, 2)
        self.assertNotIn("peak_live_logical_values", analysis.to_dict())

    def test_root_local_ends_at_its_last_semantic_use(self) -> None:
        expanded = expand_logical_module(_root_local_last_use.to_logical_module())
        lifetime = analyze_logical_lifetimes(expanded).lifetimes[0]

        self.assertEqual(lifetime.first_instruction_index, 0)
        self.assertEqual(lifetime.last_instruction_index, 0)
        self.assertEqual(lifetime.end_reason, LogicalLifetimeEndReason.LAST_USE)

    def test_entry_parameters_and_locals_have_explicit_distinct_ownership(self) -> None:
        expanded = expand_logical_module(_borrowed_and_local.to_logical_module())
        analysis = analyze_logical_lifetimes(expanded)
        parameter, local = expanded.qubits
        parameter_lifetime, local_lifetime = analysis.lifetimes

        self.assertIs(parameter.origin.call_instance_id, None)
        self.assertIs(local.origin.call_instance_id, None)
        self.assertEqual(parameter.origin.ownership, LogicalValueOwnership.ENTRY_PARAMETER)
        self.assertEqual(local.origin.ownership, LogicalValueOwnership.LOCAL)
        self.assertEqual(parameter.origin.to_dict()["ownership"], "entry_parameter")
        self.assertEqual(local.origin.to_dict()["ownership"], "local")
        self.assertEqual(parameter_lifetime.end_reason, LogicalLifetimeEndReason.PROGRAM_END)
        self.assertEqual(local_lifetime.end_reason, LogicalLifetimeEndReason.LAST_USE)

    def test_dead_entangled_local_requires_discard_instead_of_slot_reuse(self) -> None:
        expanded = expand_logical_module(_entangled_temporary_root.to_logical_module())
        lifetimes = analyze_logical_lifetimes(expanded)
        releases = analyze_quantum_releases(expanded, lifetimes)
        temporary = next(
            qubit for qubit in expanded.qubits if qubit.origin.call_instance_id is not None
        )
        release = next(
            item for item in releases.releases if item.logical_qubit_id == temporary.id
        )

        self.assertEqual(release.kind, QuantumReleaseKind.DISCARD_REQUIRED)
        self.assertEqual(release.reason, LogicalLifetimeEndReason.LAST_USE)

    def test_returned_local_is_retained_at_the_entry_return_boundary(self) -> None:
        compilation = compile_logical_module(_returned_local.to_logical_module())
        assert compilation.release_analysis is not None
        assert compilation.lifetime_analysis is not None

        release = compilation.release_analysis.releases[0]
        lifetime = compilation.lifetime_analysis.lifetimes[0]
        self.assertEqual(release.kind, QuantumReleaseKind.RETAINED)
        self.assertEqual(release.reason, LogicalLifetimeEndReason.RETURNED)
        self.assertEqual(release.after_instruction_index, lifetime.last_instruction_index)
        self.assertEqual(
            compilation.to_dict()["release_analysis"],
            compilation.release_analysis.to_dict(),
        )

    def test_semantic_liveness_peak_is_not_advertised_as_reusable_width(self) -> None:
        compilation = compile_logical_module(_burn_twice.to_logical_module())
        assert compilation.lifetime_analysis is not None

        self.assertEqual(compilation.lifetime_analysis.peak_semantically_live_values, 1)
        self.assertEqual(compilation.logical_allocation.allocated_qubit_count, 2)
        self.assertEqual(compilation.logical_allocation.peak_live_qubits, 2)
        self.assertNotEqual(
            compilation.lifetime_analysis.peak_semantically_live_values,
            compilation.logical_allocation.peak_live_qubits,
        )


if __name__ == "__main__":
    unittest.main()
