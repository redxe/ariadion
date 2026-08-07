"""Idle-decoherence channel computation and execution artifacts.

This module computes the channel parameters for a given idle duration and
T1/T2 profile, and records the result as immutable ``IdleDecoherenceEvent``
artifacts for downstream noise-impact reporting.

Physical basis
--------------
For idle duration ``t``:

* Amplitude damping probability (T1):
    ``gamma1 = 1 - exp(-t / T1)``
  This decays the |1> population and reduces off-diagonal coherences by
  ``exp(-t / (2*T1))``.

* Combined T1/T2 pure-dephasing rate:
    ``1/T2 = 1/(2*T1) + 1/Tphi``
  Additional phase-damping probability (uses Ariadion's two-Kraus convention):
    ``p_phi = 1 - exp(-2*t / Tphi)``
  where ``1/Tphi = 1/T2 - 1/(2*T1)``.
  Total coherence decay: ``exp(-t/T2)`` (verified by composing both channels).

* Only T2 given (no T1):
    ``p_phi = 1 - exp(-2*t / T2)``
  (pure phase damping; no population loss).

* Only T1 given (no T2):
  Amplitude damping only; no additional phase-damping channel.

Zero idle duration is always identity evolution (both probabilities are 0).
When T2 = 2*T1 exactly, the pure-dephasing rate is zero; only amplitude
damping is applied.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import exp

from ariadion_core import canonical_json
from ariadion_noise import AmplitudeDampingChannel, IdleDecoherenceProfile, PhaseDampingChannel

from .scheduling import IdleInterval


@dataclass(frozen=True, slots=True)
class IdleDecoherenceProvenance:
    """Structured derivation evidence for one idle-decoherence decision."""

    mode: str
    t1_ns: float | None
    t2_ns: float | None
    tphi_inverse_per_ns: float | None

    def __post_init__(self) -> None:
        valid_modes = {
            "identity",
            "t1_only",
            "t2_only",
            "t1_t2_combined",
            "t1_t2_boundary",
        }
        if self.mode not in valid_modes:
            raise ValueError("idle decoherence provenance mode is not recognized")
        for value, label in (
            (self.t1_ns, "t1_ns"),
            (self.t2_ns, "t2_ns"),
            (self.tphi_inverse_per_ns, "tphi_inverse_per_ns"),
        ):
            if value is not None and value < 0:
                raise ValueError(f"idle decoherence provenance {label} must be non-negative")

    def to_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "t1_ns": self.t1_ns,
            "t2_ns": self.t2_ns,
            "tphi_inverse_per_ns": self.tphi_inverse_per_ns,
        }


def idle_decoherence_channels_for_duration(
    duration_ns: float,
    profile: IdleDecoherenceProfile,
) -> tuple[
    AmplitudeDampingChannel | None,
    PhaseDampingChannel | None,
    float,
    float,
    tuple[str, ...],
    IdleDecoherenceProvenance,
]:
    """Compute the idle decoherence channels for ``duration_ns`` nanoseconds.

    Returns ``(amp_channel, phase_channel, gamma1, p_phi, assumptions)`` where:

    * ``amp_channel`` is an :class:`~ariadion_noise.AmplitudeDampingChannel` or
      ``None`` if T1 was not given or the idle duration is zero.
    * ``phase_channel`` is a :class:`~ariadion_noise.PhaseDampingChannel` or
      ``None`` if no additional phase damping is required.
    * ``gamma1`` is the amplitude-damping probability (``0.0`` if no T1).
    * ``p_phi`` is the additional phase-damping probability (``0.0`` if none).
    * ``assumptions`` is an ordered tuple of human-readable evidence strings.
    """

    if not isinstance(profile, IdleDecoherenceProfile):
        raise ValueError("idle_decoherence_channels_for_duration profile must be IdleDecoherenceProfile")
    if (
        isinstance(duration_ns, bool)
        or not isinstance(duration_ns, (int, float))
        or float(duration_ns) < 0
    ):
        raise ValueError("idle_decoherence_channels_for_duration duration_ns must be non-negative")

    t = float(duration_ns)
    t1 = profile.t1_ns
    t2 = profile.t2_ns

    if t == 0.0:
        return (
            None,
            None,
            0.0,
            0.0,
            ("zero idle duration: identity evolution",),
            IdleDecoherenceProvenance(
                mode="identity",
                t1_ns=t1,
                t2_ns=t2,
                tphi_inverse_per_ns=None,
            ),
        )

    assumptions: list[str] = []
    gamma1 = 0.0
    p_phi = 0.0

    mode = "identity"
    tphi_inverse_per_ns: float | None = None

    if t1 is not None:
        gamma1 = 1.0 - exp(-t / t1)
        assumptions.append(f"T1={t1}ns amplitude damping gamma1={gamma1:.6g}")
        mode = "t1_only"

    if t2 is not None:
        if t1 is not None:
            # Combined: additional pure dephasing beyond amplitude damping.
            # 1/Tphi = 1/T2 - 1/(2*T1); may be zero when T2 == 2*T1.
            t_phi_inv = 1.0 / t2 - 0.5 / t1
            if t_phi_inv > 0:
                p_phi = 1.0 - exp(-2.0 * t * t_phi_inv)
                tphi_inverse_per_ns = t_phi_inv
                mode = "t1_t2_combined"
                assumptions.append(
                    f"T2={t2}ns combined with T1: "
                    f"additional phase damping p_phi={p_phi:.6g}"
                )
            else:
                # T2 == 2*T1: amplitude damping alone gives the correct coherence decay.
                mode = "t1_t2_boundary"
                tphi_inverse_per_ns = 0.0
                assumptions.append(
                    f"T2={t2}ns equals 2*T1: amplitude damping provides full coherence decay"
                )
        else:
            # Only T2: pure phase damping.
            p_phi = 1.0 - exp(-2.0 * t / t2)
            mode = "t2_only"
            assumptions.append(f"T2={t2}ns pure phase damping p_phi={p_phi:.6g}")
    elif t1 is not None:
        assumptions.append(f"T1={t1}ns only: amplitude damping, no additional phase damping")

    amp_channel = AmplitudeDampingChannel(gamma1) if gamma1 > 0.0 else None
    phase_channel = PhaseDampingChannel(p_phi) if p_phi > 0.0 else None

    return (
        amp_channel,
        phase_channel,
        gamma1,
        p_phi,
        tuple(assumptions),
        IdleDecoherenceProvenance(
            mode=mode,
            t1_ns=t1,
            t2_ns=t2,
            tphi_inverse_per_ns=tphi_inverse_per_ns,
        ),
    )


class IdleDecoherenceEvent:
    """Immutable artifact recording where, when, and why coherence changed.

    Each event captures one idle interval on one allocated slot, the channel
    parameters computed from the declared T1/T2 constants, and the human-readable
    assumptions used. Events accumulate during density-matrix execution and are
    retained in the final result for the downstream ``NoiseImpactReport`` milestone.

    An event with ``amplitude_damping_probability == 0`` and
    ``phase_damping_probability == 0`` represents an idle interval during which
    identity evolution was applied (e.g. zero idle duration or no relevant
    time constant supplied).
    """

    __slots__ = (
        "slot",
        "interval",
        "amplitude_damping_probability",
        "phase_damping_probability",
        "assumptions",
        "provenance",
    )

    def __init__(
        self,
        slot: int,
        interval: IdleInterval,
        amplitude_damping_probability: float,
        phase_damping_probability: float,
        assumptions: tuple[str, ...],
        provenance: IdleDecoherenceProvenance,
    ) -> None:
        if isinstance(slot, bool) or not isinstance(slot, int) or slot < 0:
            raise ValueError("idle decoherence event slot must be a non-negative integer")
        if not isinstance(interval, IdleInterval):
            raise ValueError("idle decoherence event interval must be an IdleInterval")
        if (
            isinstance(amplitude_damping_probability, bool)
            or not isinstance(amplitude_damping_probability, (int, float))
            or not (0.0 <= float(amplitude_damping_probability) <= 1.0)
        ):
            raise ValueError(
                "idle decoherence event amplitude_damping_probability must be in [0, 1]"
            )
        if (
            isinstance(phase_damping_probability, bool)
            or not isinstance(phase_damping_probability, (int, float))
            or not (0.0 <= float(phase_damping_probability) <= 1.0)
        ):
            raise ValueError(
                "idle decoherence event phase_damping_probability must be in [0, 1]"
            )
        if not isinstance(assumptions, tuple) or not all(
            isinstance(a, str) for a in assumptions
        ):
            raise ValueError(
                "idle decoherence event assumptions must be a tuple of strings"
            )
        if not isinstance(provenance, IdleDecoherenceProvenance):
            raise ValueError(
                "idle decoherence event provenance must be IdleDecoherenceProvenance"
            )
        self.slot: int = slot
        self.interval: IdleInterval = interval
        self.amplitude_damping_probability: float = float(amplitude_damping_probability)
        self.phase_damping_probability: float = float(phase_damping_probability)
        self.assumptions: tuple[str, ...] = assumptions
        self.provenance: IdleDecoherenceProvenance = provenance

    def __repr__(self) -> str:
        return (
            f"IdleDecoherenceEvent(slot={self.slot!r}, interval={self.interval!r}, "
            f"amplitude_damping_probability={self.amplitude_damping_probability!r}, "
            f"phase_damping_probability={self.phase_damping_probability!r})"
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, IdleDecoherenceEvent):
            return NotImplemented
        return (
            self.slot == other.slot
            and self.interval == other.interval
            and self.amplitude_damping_probability == other.amplitude_damping_probability
            and self.phase_damping_probability == other.phase_damping_probability
            and self.assumptions == other.assumptions
            and self.provenance == other.provenance
        )

    def __hash__(self) -> int:
        return hash((
            self.slot,
            self.interval,
            self.amplitude_damping_probability,
            self.phase_damping_probability,
            self.assumptions,
            self.provenance,
        ))

    def to_dict(self) -> dict[str, object]:
        return {
            "slot": self.slot,
            "interval": self.interval.to_dict(),
            "amplitude_damping_probability": self.amplitude_damping_probability,
            "phase_damping_probability": self.phase_damping_probability,
            "assumptions": list(self.assumptions),
            "provenance": self.provenance.to_dict(),
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


__all__ = [
    "IdleDecoherenceEvent",
    "IdleDecoherenceProvenance",
    "idle_decoherence_channels_for_duration",
]
