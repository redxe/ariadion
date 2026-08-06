from __future__ import annotations

from typing import TYPE_CHECKING

from ariadion import TraceStepViewModel
from ariadion_visualization import render_circuit

if TYPE_CHECKING:
    from theonoe import StateReport


_DEFAULT_MAX_STATES = 8
_GLOBAL_PHASE_DISPLAY_EPSILON = 1e-12


def render_trace_step(
    view: TraceStepViewModel,
    *,
    max_states: int = _DEFAULT_MAX_STATES,
) -> str:
    """Render one structured trace view without managing terminal interaction."""

    if isinstance(max_states, bool) or not isinstance(max_states, int) or max_states < 1:
        raise ValueError("max_states must be a positive integer")

    operation = view.operation
    lines = [
        f"Step {view.step_number}/{view.step_count}",
        f"Operation: {operation.opcode.value} {_render_operation_qubits(view)}",
        f"IR operation ID: {view.ir_operation_id}",
    ]
    lines.extend(_render_angle(view))
    lines.extend(_render_source_and_provenance(view))
    lines.extend(
        [
            "",
            "Circuit (active gate highlighted):",
            render_circuit(
                view.circuit,
                active_operation_index=view.step_index,
            ),
            "",
        ]
    )
    lines.extend(_render_state_report("Before", view.before, max_states=max_states))
    lines.append("")
    lines.extend(_render_state_report("After", view.after, max_states=max_states))
    lines.append("")
    lines.extend(_render_basis_changes(view, max_states=max_states))
    lines.extend(_render_global_phase(view))
    lines.extend(_render_entanglement(view))
    lines.extend(_render_measurement(view))
    return "\n".join(lines)


def _render_operation_qubits(view: TraceStepViewModel) -> str:
    parts: list[str] = []
    if view.operation.controls:
        parts.append("controls " + _format_qubits(view.operation.controls))
    parts.append("targets " + _format_qubits(view.operation.targets))
    if view.operation.key is not None:
        parts.append(f"key={view.operation.key!r}")
    return "; ".join(parts)


def _render_angle(view: TraceStepViewModel) -> list[str]:
    operation = view.operation
    if operation.angle_radians is None:
        return []
    normalized = _format_angle_value(operation.angle_radians) + " rad"
    metadata = operation.angle_metadata
    if metadata is None:
        return [f"Angle: normalized {normalized}"]
    source = _format_source_angle(metadata.source_value, metadata.source_unit)
    return [f"Angle: {source} (normalized: {normalized})"]


def _format_source_angle(value: float, unit: str) -> str:
    formatted_value = _format_angle_value(value)
    if unit == "degrees":
        return formatted_value + "°"
    if unit == "radians":
        return formatted_value + " rad"
    if unit == "turns":
        return formatted_value + " turns"
    return f"{formatted_value} {unit}"


def _format_angle_value(value: float) -> str:
    return f"{value:.12g}"


def _render_source_and_provenance(view: TraceStepViewModel) -> list[str]:
    lines: list[str] = []
    if view.source is None:
        lines.append("Source: unavailable")
    else:
        location = view.source.file or "<unknown file>"
        if view.source.line is not None:
            location = f"{location}:{view.source.line}"
        if view.source.column is not None:
            location = f"{location}:{view.source.column}"
        lines.append(f"Source: {location}")
        lines.append(f"Source operation ID: {view.source.snapshot_operation_id}")
        if view.source.source_node_id is not None:
            lines.append(f"Source node ID: {view.source.source_node_id}")

    if view.provenance is not None:
        details: list[str] = []
        if view.provenance.transformation is not None:
            details.append(view.provenance.transformation)
        if view.provenance.parent_source_ids:
            parents = ", ".join(view.provenance.parent_source_ids)
            details.append(f"parents: {parents}")
        lines.append("Compiler provenance: " + "; ".join(details or ["available"]))
    return lines


def _render_state_report(
    title: str,
    report: StateReport,
    *,
    max_states: int,
) -> list[str]:
    states = report.states
    lines = [f"{title} basis states:"]
    for state in states[:max_states]:
        lines.append(
            f"  {state.label:<8} p={state.probability:.6f} "
            f"phase={state.phase_radians:+.6f} rad"
        )
    if not states:
        lines.append("  no states above the display epsilon")
    elif len(states) > max_states:
        lines.append(f"  ... {len(states) - max_states} additional basis states")
    return lines


def _render_basis_changes(
    view: TraceStepViewModel,
    *,
    max_states: int,
) -> list[str]:
    changes = view.basis_state_changes
    if not changes:
        return ["Basis changes: none"]

    lines = ["Basis changes:"]
    for change in changes[:max_states]:
        line = (
            f"  {change.label:<8} p {change.before_probability:.6f} -> "
            f"{change.after_probability:.6f} "
            f"(delta {change.probability_delta:+.6f})"
        )
        if change.phase_change_radians is not None:
            line += f"; relative phase delta {change.phase_change_radians:+.6f} rad"
        lines.append(line)
    if len(changes) > max_states:
        lines.append(f"  ... {len(changes) - max_states} additional basis changes")
    return lines


def _render_global_phase(view: TraceStepViewModel) -> list[str]:
    phase = view.global_phase_delta_radians
    if phase is None or abs(phase) <= _GLOBAL_PHASE_DISPLAY_EPSILON:
        return []
    return [f"Global phase: {phase:+.6f} rad (unobservable)"]


def _render_entanglement(view: TraceStepViewModel) -> list[str]:
    transition = view.entanglement
    lines: list[str] = []
    if transition.newly_entangled:
        lines.append("Newly entangled: " + _format_qubits(transition.newly_entangled))
    if transition.newly_separable:
        lines.append("Newly separable: " + _format_qubits(transition.newly_separable))
    return lines or ["Entanglement changes: none"]


def _render_measurement(view: TraceStepViewModel) -> list[str]:
    measurement = view.measurement
    if measurement is None:
        return []

    target_count = len(measurement.targets)
    target_text = _format_qubits(measurement.targets)
    key_text = f", key={measurement.key!r}" if measurement.key is not None else ""
    bit_order_text = f", bit order={measurement.bit_order.value}"
    if measurement.outcome is not None:
        outcome = "".join(str(bit) for bit in measurement.outcome)
        return [
            f"Measurement outcome ({target_text}{key_text}{bit_order_text}): "
            f"|{outcome}>"
        ]

    lines = [
        f"Exact measurement probabilities ({target_text}{key_text}{bit_order_text}):"
    ]
    for index, probability in enumerate(measurement.probabilities):
        lines.append(f"  |{index:0{target_count}b}> p={probability:.6f}")
    return lines


def _format_qubits(qubits: tuple[int, ...]) -> str:
    return ", ".join(f"q{qubit}" for qubit in qubits)
