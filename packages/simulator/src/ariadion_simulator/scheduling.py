"""Allocated-execution scheduling contracts for Ariadion.

Scheduling is physical-realization evidence. It does not represent source
semantics, logical quantum values, or compiler intent. A schedule assigns
concrete start and end times (in nanoseconds) to each allocated IR operation and
records the idle intervals for every allocated slot.

Gate durations must be explicitly declared. The scheduler never invents
durations; missing required timing data raises ``MissingOperationTimingError``.
"""

from __future__ import annotations

from math import isfinite

from ariadion_core import IrOperationId, ProgramId, canonical_json, require_nonempty_identifier
from ariadion_ir import CircuitIR


class MissingOperationTimingError(ValueError):
    """Raised when a required gate duration is absent from the timing profile.

    The timing profile must declare a positive finite duration for every operation
    in the circuit before a schedule can be produced.
    """

    def __init__(self, operation_id: IrOperationId) -> None:
        self.operation_id = operation_id
        super().__init__(
            f"missing timing for operation {operation_id!r}: "
            "the timing profile must declare a duration for every circuit operation"
        )


class OperationTimingError(ValueError):
    """Raised when a declared gate duration is invalid."""


class SchedulingInvariantError(ValueError):
    """Raised when a scheduling invariant is violated during construction."""


class ScheduleCircuitBindingError(ValueError):
    """Raised when a schedule does not deterministically match a circuit."""


class OperationTiming:
    """Declared or synthetic gate duration for one allocated operation.

    Durations must be positive and finite. Zero-duration gates are rejected
    because a zero duration cannot produce meaningful idle-interval evidence.
    """

    __slots__ = ("operation_id", "duration_ns")

    def __init__(self, operation_id: IrOperationId, duration_ns: float) -> None:
        require_nonempty_identifier(operation_id, label="operation timing operation_id")
        if isinstance(duration_ns, bool) or not isinstance(duration_ns, (int, float)):
            raise OperationTimingError("operation timing duration_ns must be numeric")
        duration = float(duration_ns)
        if not isfinite(duration) or duration <= 0:
            raise OperationTimingError(
                "operation timing duration_ns must be a positive finite number"
            )
        self.operation_id: IrOperationId = operation_id
        self.duration_ns: float = duration

    def __repr__(self) -> str:
        return f"OperationTiming({self.operation_id!r}, {self.duration_ns!r})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, OperationTiming):
            return NotImplemented
        return self.operation_id == other.operation_id and self.duration_ns == other.duration_ns

    def __hash__(self) -> int:
        return hash((self.operation_id, self.duration_ns))

    def to_dict(self) -> dict[str, object]:
        return {"operation_id": self.operation_id, "duration_ns": self.duration_ns}

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


class ScheduledOperation:
    """An allocated operation pinned to its ASAP start and end times.

    ``start_ns`` and ``end_ns`` are non-negative finite values in nanoseconds.
    ``end_ns`` must strictly exceed ``start_ns``; zero-duration operations are
    not representable because they produce no meaningful idle-interval evidence.
    """

    __slots__ = ("operation_id", "start_ns", "end_ns")

    def __init__(
        self,
        operation_id: IrOperationId,
        start_ns: float,
        end_ns: float,
    ) -> None:
        require_nonempty_identifier(operation_id, label="scheduled operation operation_id")
        if not isinstance(start_ns, (int, float)) or isinstance(start_ns, bool):
            raise SchedulingInvariantError("scheduled operation start_ns must be numeric")
        if not isinstance(end_ns, (int, float)) or isinstance(end_ns, bool):
            raise SchedulingInvariantError("scheduled operation end_ns must be numeric")
        start = float(start_ns)
        end = float(end_ns)
        if not isfinite(start) or start < 0:
            raise SchedulingInvariantError(
                "scheduled operation start_ns must be a non-negative finite number"
            )
        if not isfinite(end) or end <= start:
            raise SchedulingInvariantError(
                "scheduled operation end_ns must be a finite number greater than start_ns"
            )
        self.operation_id: IrOperationId = operation_id
        self.start_ns: float = start
        self.end_ns: float = end

    @property
    def duration_ns(self) -> float:
        return self.end_ns - self.start_ns

    def __repr__(self) -> str:
        return (
            f"ScheduledOperation({self.operation_id!r}, "
            f"start_ns={self.start_ns!r}, end_ns={self.end_ns!r})"
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ScheduledOperation):
            return NotImplemented
        return (
            self.operation_id == other.operation_id
            and self.start_ns == other.start_ns
            and self.end_ns == other.end_ns
        )

    def __hash__(self) -> int:
        return hash((self.operation_id, self.start_ns, self.end_ns))

    def to_dict(self) -> dict[str, object]:
        return {
            "operation_id": self.operation_id,
            "start_ns": self.start_ns,
            "end_ns": self.end_ns,
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


class IdleInterval:
    """One continuous idle period for one allocated slot.

    ``start_ns`` and ``end_ns`` are non-negative finite values in nanoseconds.
    ``end_ns`` must strictly exceed ``start_ns``.
    """

    __slots__ = ("slot", "start_ns", "end_ns")

    def __init__(self, slot: int, start_ns: float, end_ns: float) -> None:
        if isinstance(slot, bool) or not isinstance(slot, int) or slot < 0:
            raise SchedulingInvariantError("idle interval slot must be a non-negative integer")
        if not isinstance(start_ns, (int, float)) or isinstance(start_ns, bool):
            raise SchedulingInvariantError("idle interval start_ns must be numeric")
        if not isinstance(end_ns, (int, float)) or isinstance(end_ns, bool):
            raise SchedulingInvariantError("idle interval end_ns must be numeric")
        start = float(start_ns)
        end = float(end_ns)
        if not isfinite(start) or start < 0:
            raise SchedulingInvariantError(
                "idle interval start_ns must be a non-negative finite number"
            )
        if not isfinite(end) or end <= start:
            raise SchedulingInvariantError(
                "idle interval end_ns must be a finite number greater than start_ns"
            )
        self.slot: int = slot
        self.start_ns: float = start
        self.end_ns: float = end

    @property
    def duration_ns(self) -> float:
        return self.end_ns - self.start_ns

    def __repr__(self) -> str:
        return (
            f"IdleInterval(slot={self.slot!r}, "
            f"start_ns={self.start_ns!r}, end_ns={self.end_ns!r})"
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, IdleInterval):
            return NotImplemented
        return (
            self.slot == other.slot
            and self.start_ns == other.start_ns
            and self.end_ns == other.end_ns
        )

    def __hash__(self) -> int:
        return hash((self.slot, self.start_ns, self.end_ns))

    def to_dict(self) -> dict[str, object]:
        return {"slot": self.slot, "start_ns": self.start_ns, "end_ns": self.end_ns}

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


class ExecutionSchedule:
    """Immutable ASAP schedule pairing every operation with timing evidence.

    Records all scheduled operations and the idle intervals for every allocated
    slot. ``peak_duration_ns`` is the earliest time at which all slots are free
    (the end of the last operation across all slots).
    """

    __slots__ = ("program_id", "scheduled_operations", "idle_intervals", "peak_duration_ns")

    def __init__(
        self,
        program_id: ProgramId,
        scheduled_operations: tuple[ScheduledOperation, ...],
        idle_intervals: tuple[IdleInterval, ...],
        peak_duration_ns: float,
    ) -> None:
        require_nonempty_identifier(program_id, label="execution schedule program_id")
        if not isinstance(scheduled_operations, tuple):
            raise SchedulingInvariantError(
                "execution schedule scheduled_operations must be a tuple"
            )
        if not all(isinstance(op, ScheduledOperation) for op in scheduled_operations):
            raise SchedulingInvariantError(
                "execution schedule scheduled_operations must contain ScheduledOperation values"
            )
        if not isinstance(idle_intervals, tuple):
            raise SchedulingInvariantError("execution schedule idle_intervals must be a tuple")
        if not all(isinstance(ii, IdleInterval) for ii in idle_intervals):
            raise SchedulingInvariantError(
                "execution schedule idle_intervals must contain IdleInterval values"
            )
        if (
            isinstance(peak_duration_ns, bool)
            or not isinstance(peak_duration_ns, (int, float))
            or not isfinite(float(peak_duration_ns))
            or float(peak_duration_ns) < 0
        ):
            raise SchedulingInvariantError(
                "execution schedule peak_duration_ns must be a non-negative finite number"
            )
        peak = float(peak_duration_ns)

        operation_ids = [op.operation_id for op in scheduled_operations]
        duplicate_operation_ids = {
            operation_id
            for operation_id in operation_ids
            if operation_ids.count(operation_id) > 1
        }
        if duplicate_operation_ids:
            duplicates = ", ".join(sorted(duplicate_operation_ids))
            raise SchedulingInvariantError(
                "execution schedule scheduled_operations must not contain duplicate "
                f"operation IDs (duplicates: {duplicates})"
            )

        for operation in scheduled_operations:
            if operation.end_ns > peak:
                raise SchedulingInvariantError(
                    "execution schedule scheduled operation end_ns must be less than or "
                    "equal to peak_duration_ns"
                )

        for interval in idle_intervals:
            if interval.end_ns > peak:
                raise SchedulingInvariantError(
                    "execution schedule idle interval end_ns must be less than or equal "
                    "to peak_duration_ns"
                )

        for slot in {interval.slot for interval in idle_intervals}:
            intervals_for_slot = sorted(
                (interval for interval in idle_intervals if interval.slot == slot),
                key=lambda interval: interval.start_ns,
            )
            for prior, current in zip(intervals_for_slot, intervals_for_slot[1:], strict=False):
                if current.start_ns < prior.end_ns:
                    raise SchedulingInvariantError(
                        "execution schedule idle intervals must not overlap for the same slot"
                    )

        self.program_id: ProgramId = program_id
        self.scheduled_operations: tuple[ScheduledOperation, ...] = scheduled_operations
        self.idle_intervals: tuple[IdleInterval, ...] = idle_intervals
        self.peak_duration_ns: float = peak

    def timing_for_operation(self, operation_id: IrOperationId) -> ScheduledOperation | None:
        """Return the scheduled timing for an operation, or ``None`` if not found."""
        for op in self.scheduled_operations:
            if op.operation_id == operation_id:
                return op
        return None

    def idle_intervals_for_slot(self, slot: int) -> tuple[IdleInterval, ...]:
        """Return idle intervals for one allocated slot, sorted by start time."""
        return tuple(
            sorted(
                (ii for ii in self.idle_intervals if ii.slot == slot),
                key=lambda ii: ii.start_ns,
            )
        )

    def __repr__(self) -> str:
        return (
            f"ExecutionSchedule(program_id={self.program_id!r}, "
            f"scheduled_operations={self.scheduled_operations!r}, "
            f"idle_intervals={self.idle_intervals!r}, "
            f"peak_duration_ns={self.peak_duration_ns!r})"
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ExecutionSchedule):
            return NotImplemented
        return (
            self.program_id == other.program_id
            and
            self.scheduled_operations == other.scheduled_operations
            and self.idle_intervals == other.idle_intervals
            and self.peak_duration_ns == other.peak_duration_ns
        )

    def __hash__(self) -> int:
        return hash((self.program_id, self.scheduled_operations, self.idle_intervals, self.peak_duration_ns))

    def to_dict(self) -> dict[str, object]:
        return {
            "program_id": self.program_id,
            "scheduled_operations": [op.to_dict() for op in self.scheduled_operations],
            "idle_intervals": [ii.to_dict() for ii in self.idle_intervals],
            "peak_duration_ns": self.peak_duration_ns,
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


def schedule_asap(
    circuit: CircuitIR,
    timing_profile: dict[IrOperationId, float],
) -> ExecutionSchedule:
    """Build a deterministic ASAP execution schedule for an allocated circuit.

    For each operation in IR topological order:

    ``start = max(availability of every target and control slot)``
    ``end   = start + duration``

    Disjoint operations (no shared slots) may overlap in time. Gate durations
    must be explicitly declared; any missing duration raises
    ``MissingOperationTimingError``.

    The resulting schedule records every scheduled operation and every idle
    interval for every allocated slot from 0 to ``peak_duration_ns``.
    """

    if not isinstance(circuit, CircuitIR):
        raise ValueError("schedule_asap circuit must be CircuitIR")
    if not isinstance(timing_profile, dict):
        raise ValueError("schedule_asap timing_profile must be a dict")

    # For each slot, the earliest time it is free for the next operation.
    slot_available: dict[int, float] = {slot: 0.0 for slot in range(circuit.qubit_count)}

    scheduled_operations: list[ScheduledOperation] = []

    # Track (start, end) busy intervals per slot for idle-interval computation.
    slot_busy: dict[int, list[tuple[float, float]]] = {
        slot: [] for slot in range(circuit.qubit_count)
    }

    for operation in circuit.operations:
        duration = timing_profile.get(operation.id)
        if duration is None:
            raise MissingOperationTimingError(operation.id)

        # Validate the declared duration eagerly.
        if (
            isinstance(duration, bool)
            or not isinstance(duration, (int, float))
            or not isfinite(float(duration))
            or float(duration) <= 0
        ):
            raise OperationTimingError(
                f"declared duration for operation {operation.id!r} must be a positive finite "
                f"number, got {duration!r}"
            )
        duration_f = float(duration)

        involved = list(operation.targets) + list(operation.controls)
        start_ns = max((slot_available[s] for s in involved), default=0.0)
        end_ns = start_ns + duration_f

        scheduled_operations.append(
            ScheduledOperation(operation_id=operation.id, start_ns=start_ns, end_ns=end_ns)
        )
        for slot in involved:
            slot_available[slot] = end_ns
            slot_busy[slot].append((start_ns, end_ns))

    peak_duration_ns = max(slot_available.values(), default=0.0)

    # Compute idle intervals: gaps before the first operation, between operations,
    # and after the last operation up to peak_duration_ns.
    idle_intervals: list[IdleInterval] = []
    for slot in range(circuit.qubit_count):
        busy = sorted(slot_busy[slot])
        cursor = 0.0
        for start, end in busy:
            if start > cursor:
                idle_intervals.append(
                    IdleInterval(slot=slot, start_ns=cursor, end_ns=start)
                )
            cursor = max(cursor, end)
        if cursor < peak_duration_ns:
            idle_intervals.append(
                IdleInterval(slot=slot, start_ns=cursor, end_ns=peak_duration_ns)
            )

    return ExecutionSchedule(
        program_id=circuit.id,
        scheduled_operations=tuple(scheduled_operations),
        idle_intervals=tuple(idle_intervals),
        peak_duration_ns=peak_duration_ns,
    )


def validate_schedule_for_circuit(circuit: CircuitIR, schedule: ExecutionSchedule) -> None:
    """Validate deterministic one-to-one schedule coverage for one circuit.

    Raises ``ScheduleCircuitBindingError`` when the schedule and circuit cannot be
    safely paired for scheduled execution.
    """

    if not isinstance(circuit, CircuitIR):
        raise ValueError("schedule validation circuit must be CircuitIR")
    if not isinstance(schedule, ExecutionSchedule):
        raise ValueError("schedule validation schedule must be ExecutionSchedule")
    if schedule.program_id != circuit.id:
        raise ScheduleCircuitBindingError(
            "execution schedule program_id must match the circuit program ID"
        )

    circuit_operation_ids = [operation.id for operation in circuit.operations]
    scheduled_operation_ids = [operation.operation_id for operation in schedule.scheduled_operations]

    if len(scheduled_operation_ids) != len(set(scheduled_operation_ids)):
        raise ScheduleCircuitBindingError(
            "execution schedule contains duplicate scheduled operation IDs"
        )

    missing_operation_ids = sorted(set(circuit_operation_ids) - set(scheduled_operation_ids))
    extra_operation_ids = sorted(set(scheduled_operation_ids) - set(circuit_operation_ids))
    if missing_operation_ids or extra_operation_ids:
        messages: list[str] = []
        if missing_operation_ids:
            messages.append("missing IDs: " + ", ".join(missing_operation_ids))
        if extra_operation_ids:
            messages.append("extra IDs: " + ", ".join(extra_operation_ids))
        raise ScheduleCircuitBindingError(
            "execution schedule and circuit operation coverage mismatch ("
            + "; ".join(messages)
            + ")"
        )

    if scheduled_operation_ids != circuit_operation_ids:
        raise ScheduleCircuitBindingError(
            "execution schedule operation order must exactly match circuit operation order"
        )


__all__ = [
    "ExecutionSchedule",
    "IdleInterval",
    "MissingOperationTimingError",
    "OperationTiming",
    "OperationTimingError",
    "ScheduleCircuitBindingError",
    "ScheduledOperation",
    "SchedulingInvariantError",
    "schedule_asap",
    "validate_schedule_for_circuit",
]
