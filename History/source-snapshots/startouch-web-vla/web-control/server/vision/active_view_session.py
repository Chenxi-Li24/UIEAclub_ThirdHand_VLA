"""Pure identity-bound state transitions for one active-view request."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Callable, Mapping, Protocol
from uuid import UUID, uuid4

import numpy as np

from .active_view_types import (
    DepthQuality,
    ObservationMoveProposal,
    validated_evidence_ids,
)
from .types import FrameStamp, InvalidDataError, PoseEstimate


class InvalidTransition(RuntimeError):
    """Raised when an event cannot advance the current session state."""


class ActiveViewPhase(str, Enum):
    IDLE = "idle"
    TARGET_LOCKED = "target_locked"
    COARSE_VIEW_PLANNED = "coarse_view_planned"
    MOVE_AUTHORIZED = "move_authorized"
    MOVING_TO_VIEW = "moving_to_view"
    SETTLING = "settling"
    VERIFYING_IDENTITY = "verifying_identity"
    ACQUIRING_DEPTH = "acquiring_depth"
    REFINE_VIEW = "refine_view"
    GRASP_PREVIEW = "grasp_preview"
    WAITING_OPERATOR_CONFIRMATION = "waiting_operator_confirmation"
    READY_FOR_EXISTING_GRASP_GATE = "ready_for_existing_grasp_gate"
    ABORTED = "aborted"
    COMPLETE = "complete"


def _session_id(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise InvalidDataError("active-view event requires a session_id")
    return value


def _identity_id(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InvalidDataError("active-view identity_id must be non-negative")
    return value


def _timestamp(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InvalidDataError("active-view event timestamp must be non-negative")
    return value


@dataclass(frozen=True)
class LockTarget:
    session_id: str
    identity_id: int
    calibration_ids: tuple[str, ...]
    observed_ns: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "session_id", _session_id(self.session_id))
        object.__setattr__(self, "identity_id", _identity_id(self.identity_id))
        object.__setattr__(self, "calibration_ids", validated_evidence_ids(self.calibration_ids))
        object.__setattr__(self, "observed_ns", _timestamp(self.observed_ns))


@dataclass(frozen=True)
class ProposalReady:
    session_id: str
    proposal: ObservationMoveProposal

    def __post_init__(self) -> None:
        object.__setattr__(self, "session_id", _session_id(self.session_id))
        if not isinstance(self.proposal, ObservationMoveProposal):
            raise InvalidDataError("ProposalReady requires an observation proposal")


@dataclass(frozen=True)
class MoveStarted:
    session_id: str
    request_id: str
    observed_ns: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "session_id", _session_id(self.session_id))
        if not isinstance(self.request_id, str) or not self.request_id:
            raise InvalidDataError("MoveStarted requires a request_id")
        object.__setattr__(self, "observed_ns", _timestamp(self.observed_ns))


@dataclass(frozen=True)
class OperatorConfirmed:
    session_id: str
    proposal_id: str
    observed_ns: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "session_id", _session_id(self.session_id))
        if not isinstance(self.proposal_id, str) or not self.proposal_id:
            raise InvalidDataError("OperatorConfirmed requires a proposal_id")
        object.__setattr__(self, "observed_ns", _timestamp(self.observed_ns))


@dataclass(frozen=True)
class MoveCompleted:
    session_id: str
    request_id: str
    observed_ns: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "session_id", _session_id(self.session_id))
        if not isinstance(self.request_id, str) or not self.request_id:
            raise InvalidDataError("MoveCompleted requires a request_id")
        object.__setattr__(self, "observed_ns", _timestamp(self.observed_ns))


@dataclass(frozen=True)
class Settled:
    session_id: str
    observed_ns: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "session_id", _session_id(self.session_id))
        object.__setattr__(self, "observed_ns", _timestamp(self.observed_ns))


@dataclass(frozen=True)
class IdentityObserved:
    session_id: str
    identity_id: int
    confirmed: bool
    observed_ns: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "session_id", _session_id(self.session_id))
        object.__setattr__(self, "identity_id", _identity_id(self.identity_id))
        if not isinstance(self.confirmed, bool):
            raise InvalidDataError("identity confirmation must be a boolean")
        object.__setattr__(self, "observed_ns", _timestamp(self.observed_ns))


@dataclass(frozen=True)
class DepthObserved:
    session_id: str
    identity_id: int
    pose: PoseEstimate
    quality: DepthQuality
    observed_ns: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "session_id", _session_id(self.session_id))
        object.__setattr__(self, "identity_id", _identity_id(self.identity_id))
        if not isinstance(self.pose, PoseEstimate):
            raise InvalidDataError("DepthObserved requires a pose estimate")
        if not isinstance(self.quality, DepthQuality):
            raise InvalidDataError("DepthObserved requires depth quality")
        object.__setattr__(self, "observed_ns", _timestamp(self.observed_ns))


@dataclass(frozen=True)
class Cancel:
    session_id: str
    reason: str
    observed_ns: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "session_id", _session_id(self.session_id))
        if not isinstance(self.reason, str) or not self.reason:
            raise InvalidDataError("cancellation requires a reason")
        object.__setattr__(self, "observed_ns", _timestamp(self.observed_ns))


@dataclass(frozen=True)
class EvidenceExpired:
    session_id: str
    evidence_id: str
    observed_ns: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "session_id", _session_id(self.session_id))
        evidence_id = validated_evidence_ids((self.evidence_id,))[0]
        object.__setattr__(self, "evidence_id", evidence_id)
        object.__setattr__(self, "observed_ns", _timestamp(self.observed_ns))


@dataclass(frozen=True)
class DepthStabilityDecision:
    stable: bool
    center_m: np.ndarray = field(compare=False)
    mad_m: np.ndarray = field(compare=False)
    samples: tuple[PoseEstimate, ...]
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.stable, bool):
            raise InvalidDataError("depth stability must be a boolean")
        center = np.array(self.center_m, dtype=float, copy=True)
        mad = np.array(self.mad_m, dtype=float, copy=True)
        if center.shape != (3,) or mad.shape != (3,) or not np.isfinite(center).all():
            raise InvalidDataError("depth stability center and MAD must be finite three-vectors")
        if not np.isfinite(mad).all() or np.any(mad < 0.0):
            raise InvalidDataError("depth stability MAD must be finite and non-negative")
        samples = tuple(self.samples)
        if not samples or any(not isinstance(sample, PoseEstimate) for sample in samples):
            raise InvalidDataError("depth stability requires pose samples")
        reasons = tuple(self.reasons)
        if self.stable and reasons:
            raise InvalidDataError("stable depth cannot have rejection reasons")
        if not self.stable and not reasons:
            raise InvalidDataError("unstable depth requires reasons")
        center.setflags(write=False)
        mad.setflags(write=False)
        object.__setattr__(self, "center_m", center)
        object.__setattr__(self, "mad_m", mad)
        object.__setattr__(self, "samples", samples)
        object.__setattr__(self, "reasons", reasons)


@dataclass(frozen=True)
class DepthStabilityWindow:
    sample_count: int
    max_center_deviation_m: float
    max_axis_mad_m: float
    identity_id: int | None = None
    samples: tuple[PoseEstimate, ...] = ()

    def __post_init__(self) -> None:
        if isinstance(self.sample_count, bool) or not isinstance(self.sample_count, int):
            raise InvalidDataError("depth stability sample count must be an integer")
        if self.sample_count <= 0:
            raise InvalidDataError("depth stability sample count must be positive")
        limits = np.asarray(
            [self.max_center_deviation_m, self.max_axis_mad_m],
            dtype=float,
        )
        if not np.isfinite(limits).all() or np.any(limits <= 0.0):
            raise InvalidDataError("depth stability limits must be finite and positive")
        if self.identity_id is not None:
            _identity_id(self.identity_id)
        samples = tuple(self.samples)
        if any(not isinstance(sample, PoseEstimate) for sample in samples):
            raise InvalidDataError("depth stability window contains an invalid pose")
        if len(samples) > self.sample_count:
            raise InvalidDataError("depth stability window exceeds its configured bound")
        if samples and self.identity_id is None:
            raise InvalidDataError("depth stability samples require an identity")
        object.__setattr__(self, "max_center_deviation_m", float(limits[0]))
        object.__setattr__(self, "max_axis_mad_m", float(limits[1]))
        object.__setattr__(self, "samples", samples)

    def add(self, identity_id: int, pose: PoseEstimate) -> DepthStabilityDecision:
        identity = _identity_id(identity_id)
        if not isinstance(pose, PoseEstimate):
            raise InvalidDataError("depth stability requires a pose estimate")
        reset_reason: str | None = None
        if self.identity_id != identity:
            samples = (pose,)
            reset_reason = "identity_changed"
        elif self.samples and pose.calibration_id != self.samples[-1].calibration_id:
            samples = (pose,)
            reset_reason = "calibration_changed"
        elif self.samples and pose.stamp.monotonic_ns <= self.samples[-1].stamp.monotonic_ns:
            samples = (pose,)
            reset_reason = "stale_pose"
        else:
            samples = (self.samples + (pose,))[-self.sample_count :]

        centers = np.asarray([sample.xyz_m for sample in samples], dtype=float)
        center = np.median(centers, axis=0)
        deviation = np.linalg.norm(centers - center, axis=1)
        mad = np.median(np.abs(centers - center), axis=0)
        reasons: list[str] = []
        if reset_reason is not None and self.identity_id is not None:
            reasons.append(reset_reason)
        if len(samples) < self.sample_count:
            reasons.append("insufficient_stable_samples")
        if float(np.max(deviation)) > self.max_center_deviation_m:
            reasons.append("center_deviation_exceeded")
        if float(np.max(mad)) > self.max_axis_mad_m:
            reasons.append("axis_mad_exceeded")
        return DepthStabilityDecision(
            stable=not reasons,
            center_m=center,
            mad_m=mad,
            samples=samples,
            reasons=tuple(reasons),
        )


class ActiveViewSessionConfig(Protocol):
    stable_sample_count: int
    max_center_deviation_m: float
    max_axis_mad_m: float
    max_refinement_steps: int


@dataclass(frozen=True)
class ActiveViewSession:
    session_id: str
    identity_id: int
    evidence_ids: tuple[str, ...]
    phase: ActiveViewPhase
    created_ns: int
    updated_ns: int
    proposal: ObservationMoveProposal | None = None
    request_id: str | None = None
    identity_confirmations: int = 0
    refinement_steps: int = 0
    depth_samples: tuple[PoseEstimate, ...] = ()
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "session_id", _session_id(self.session_id))
        object.__setattr__(self, "identity_id", _identity_id(self.identity_id))
        object.__setattr__(self, "evidence_ids", validated_evidence_ids(self.evidence_ids))
        if not isinstance(self.phase, ActiveViewPhase):
            raise InvalidDataError("active-view session phase is invalid")
        created_ns = _timestamp(self.created_ns)
        updated_ns = _timestamp(self.updated_ns)
        if updated_ns < created_ns:
            raise InvalidDataError("active-view session time cannot go backwards")
        if self.proposal is not None and not isinstance(self.proposal, ObservationMoveProposal):
            raise InvalidDataError("active-view session proposal is invalid")
        if self.request_id is not None and (
            not isinstance(self.request_id, str) or not self.request_id
        ):
            raise InvalidDataError("active-view session request_id is invalid")
        counters = (self.identity_confirmations, self.refinement_steps)
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in counters
        ):
            raise InvalidDataError("active-view session counters must be non-negative")
        samples = tuple(self.depth_samples)
        if any(not isinstance(sample, PoseEstimate) for sample in samples):
            raise InvalidDataError("active-view session contains invalid depth samples")
        reasons = tuple(self.reasons)
        if self.phase is ActiveViewPhase.ABORTED and not reasons:
            raise InvalidDataError("aborted active-view session requires reasons")
        if self.phase is not ActiveViewPhase.ABORTED and reasons:
            raise InvalidDataError("non-aborted active-view session cannot have reasons")
        object.__setattr__(self, "created_ns", created_ns)
        object.__setattr__(self, "updated_ns", updated_ns)
        object.__setattr__(self, "depth_samples", samples)
        object.__setattr__(self, "reasons", reasons)

    @classmethod
    def start(
        cls,
        session_id: str,
        identity_id: int,
        calibration_ids: tuple[str, ...],
        now_ns: int,
    ) -> "ActiveViewSession":
        return cls(
            session_id=session_id,
            identity_id=identity_id,
            evidence_ids=calibration_ids,
            phase=ActiveViewPhase.TARGET_LOCKED,
            created_ns=now_ns,
            updated_ns=now_ns,
        )

    def _abort(self, reason: str, observed_ns: int) -> "ActiveViewSession":
        return replace(
            self,
            phase=ActiveViewPhase.ABORTED,
            updated_ns=max(self.updated_ns, observed_ns),
            proposal=None,
            request_id=None,
            depth_samples=(),
            reasons=(reason,),
        )

    def transition(
        self,
        event: Any,
        config: ActiveViewSessionConfig,
    ) -> "ActiveViewSession":
        if getattr(event, "session_id", None) != self.session_id:
            raise InvalidTransition("event session does not match active session")
        if self.phase in {ActiveViewPhase.ABORTED, ActiveViewPhase.COMPLETE}:
            raise InvalidTransition("terminal sessions cannot advance")
        if isinstance(event, Cancel):
            return self._abort(event.reason, event.observed_ns)
        if isinstance(event, EvidenceExpired):
            return self._abort("evidence_expired", event.observed_ns)
        observed_ns = getattr(event, "observed_ns", None)
        if observed_ns is not None and observed_ns <= self.updated_ns:
            raise InvalidTransition("stale event cannot advance active session")

        if self.phase is ActiveViewPhase.TARGET_LOCKED and isinstance(event, ProposalReady):
            return self._on_initial_proposal(event)
        if self.phase is ActiveViewPhase.REFINE_VIEW and isinstance(event, ProposalReady):
            return self._on_refinement_proposal(event, config)
        planned_phases = {ActiveViewPhase.COARSE_VIEW_PLANNED, ActiveViewPhase.REFINE_VIEW}
        if self.phase in planned_phases and isinstance(event, OperatorConfirmed):
            return self._on_operator_confirmed(event)
        if self.phase in planned_phases and isinstance(event, MoveStarted):
            raise InvalidTransition("OperatorConfirmed is required before MoveStarted")
        if self.phase is ActiveViewPhase.MOVE_AUTHORIZED and isinstance(event, MoveStarted):
            return self._on_move_started(event)
        if self.phase is ActiveViewPhase.MOVING_TO_VIEW and isinstance(event, MoveCompleted):
            return self._on_move_completed(event)
        if self.phase is ActiveViewPhase.SETTLING and isinstance(event, Settled):
            return replace(
                self,
                phase=ActiveViewPhase.VERIFYING_IDENTITY,
                updated_ns=event.observed_ns,
                identity_confirmations=0,
                depth_samples=(),
            )
        if self.phase is ActiveViewPhase.VERIFYING_IDENTITY and isinstance(
            event, IdentityObserved
        ):
            return self._on_identity(event)
        if self.phase is ActiveViewPhase.ACQUIRING_DEPTH and isinstance(event, IdentityObserved):
            if event.identity_id != self.identity_id or not event.confirmed:
                reason = (
                    "target_identity_changed"
                    if event.identity_id != self.identity_id
                    else "target_identity_ambiguous"
                )
                return self._abort(reason, event.observed_ns)
            return replace(self, updated_ns=event.observed_ns)
        if self.phase is ActiveViewPhase.ACQUIRING_DEPTH and isinstance(event, DepthObserved):
            return self._on_depth(event, config)
        if self.phase is ActiveViewPhase.MOVING_TO_VIEW:
            raise InvalidTransition(
                f"{type(event).__name__} is invalid while moving; MoveCompleted is required"
            )
        raise InvalidTransition(f"{type(event).__name__} is invalid in {self.phase.value}")

    def _on_initial_proposal(self, event: ProposalReady) -> "ActiveViewSession":
        proposal = event.proposal
        if proposal.identity_id != self.identity_id:
            return self._abort("target_identity_changed", self.updated_ns)
        if proposal.expires_ns <= self.updated_ns:
            return self._abort("proposal_expired", self.updated_ns)
        evidence = tuple(dict.fromkeys(self.evidence_ids + proposal.evidence_ids))
        if proposal.kind == "none":
            if proposal.reasons == ("observation_already_sufficient",):
                return replace(
                    self,
                    phase=ActiveViewPhase.VERIFYING_IDENTITY,
                    proposal=proposal,
                    evidence_ids=evidence,
                )
            return self._abort(proposal.reasons[0], self.updated_ns)
        if proposal.kind != "coarse_pose":
            raise InvalidTransition("initial active-view proposal must be coarse")
        return replace(
            self,
            phase=ActiveViewPhase.COARSE_VIEW_PLANNED,
            proposal=proposal,
            evidence_ids=evidence,
        )

    def _on_refinement_proposal(
        self,
        event: ProposalReady,
        config: ActiveViewSessionConfig,
    ) -> "ActiveViewSession":
        proposal = event.proposal
        if proposal.identity_id != self.identity_id:
            return self._abort("target_identity_changed", self.updated_ns)
        if proposal.kind == "none":
            return self._abort(proposal.reasons[0], self.updated_ns)
        if proposal.kind != "refine_delta":
            raise InvalidTransition("refinement phase requires a delta proposal")
        if self.refinement_steps >= config.max_refinement_steps:
            return self._abort("view_refinement_exhausted", self.updated_ns)
        evidence = tuple(dict.fromkeys(self.evidence_ids + proposal.evidence_ids))
        return replace(self, proposal=proposal, evidence_ids=evidence)

    def _on_move_started(self, event: MoveStarted) -> "ActiveViewSession":
        if self.proposal is None:
            raise InvalidTransition("MoveStarted requires a ready proposal")
        if event.observed_ns >= self.proposal.expires_ns:
            return self._abort("proposal_expired", event.observed_ns)
        refinement_steps = self.refinement_steps + int(self.proposal.kind == "refine_delta")
        return replace(
            self,
            phase=ActiveViewPhase.MOVING_TO_VIEW,
            updated_ns=event.observed_ns,
            request_id=event.request_id,
            identity_confirmations=0,
            refinement_steps=refinement_steps,
            depth_samples=(),
        )

    def _on_operator_confirmed(self, event: OperatorConfirmed) -> "ActiveViewSession":
        if self.proposal is None:
            raise InvalidTransition("OperatorConfirmed requires a ready proposal")
        if event.observed_ns >= self.proposal.expires_ns:
            return self._abort("proposal_expired", event.observed_ns)
        return replace(
            self,
            phase=ActiveViewPhase.MOVE_AUTHORIZED,
            updated_ns=event.observed_ns,
        )

    def _on_move_completed(self, event: MoveCompleted) -> "ActiveViewSession":
        if event.request_id != self.request_id:
            raise InvalidTransition("movement completion request does not match")
        return replace(
            self,
            phase=ActiveViewPhase.SETTLING,
            updated_ns=event.observed_ns,
            request_id=None,
        )

    def _on_identity(self, event: IdentityObserved) -> "ActiveViewSession":
        if event.identity_id != self.identity_id:
            return self._abort("target_identity_changed", event.observed_ns)
        if not event.confirmed:
            return self._abort("target_identity_ambiguous", event.observed_ns)
        confirmations = self.identity_confirmations + 1
        phase = (
            ActiveViewPhase.ACQUIRING_DEPTH
            if confirmations >= 2
            else ActiveViewPhase.VERIFYING_IDENTITY
        )
        return replace(
            self,
            phase=phase,
            updated_ns=event.observed_ns,
            identity_confirmations=confirmations,
        )

    def _on_depth(
        self,
        event: DepthObserved,
        config: ActiveViewSessionConfig,
    ) -> "ActiveViewSession":
        if event.identity_id != self.identity_id:
            return self._abort("target_identity_changed", event.observed_ns)
        if event.pose.calibration_id not in self.evidence_ids:
            return self._abort("evidence_changed", event.observed_ns)
        if (
            event.pose.stamp.monotonic_ns < self.updated_ns
            or event.pose.stamp.monotonic_ns > event.observed_ns
        ):
            return self._abort("stale_depth_observation", event.observed_ns)
        if not event.quality.acceptable:
            if self.refinement_steps >= config.max_refinement_steps:
                return self._abort("view_refinement_exhausted", event.observed_ns)
            return replace(
                self,
                phase=ActiveViewPhase.REFINE_VIEW,
                updated_ns=event.observed_ns,
                proposal=None,
                identity_confirmations=0,
                depth_samples=(),
            )
        if self.depth_samples:
            prior = np.median(np.asarray([sample.xyz_m for sample in self.depth_samples]), axis=0)
            if np.linalg.norm(event.pose.xyz_m - prior) > config.max_center_deviation_m:
                return self._abort("target_moved", event.observed_ns)
        window = DepthStabilityWindow(
            config.stable_sample_count,
            config.max_center_deviation_m,
            config.max_axis_mad_m,
            identity_id=self.identity_id,
            samples=self.depth_samples,
        )
        decision = window.add(self.identity_id, event.pose)
        phase = (
            ActiveViewPhase.GRASP_PREVIEW
            if decision.stable
            else ActiveViewPhase.ACQUIRING_DEPTH
        )
        return replace(
            self,
            phase=phase,
            updated_ns=event.observed_ns,
            depth_samples=decision.samples,
        )


def _uuid(value: Any, name: str) -> str:
    if not isinstance(value, str) or len(value) != 36:
        raise InvalidDataError(f"{name} must be a canonical UUID")
    try:
        parsed = UUID(value)
    except (ValueError, TypeError, AttributeError) as exc:
        raise InvalidDataError(f"{name} must be a canonical UUID") from exc
    if str(parsed) != value or parsed.variant != UUID(value).variant:
        raise InvalidDataError(f"{name} must be a canonical UUID")
    return value


def _coordinator_event_base() -> dict[str, Any]:
    return {
        "active_view_execution_enabled": False,
        "robot_execution_enabled": False,
    }


class ActiveViewSessionCoordinator:
    """Own one active-view session and correlate ID-only protocol commands."""

    def __init__(
        self,
        config: ActiveViewSessionConfig,
        *,
        evidence_ids: tuple[str, ...],
        proposal_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.config = config
        self.evidence_ids = validated_evidence_ids(evidence_ids)
        self.proposal_id_factory = proposal_id_factory or (lambda: str(uuid4()))
        self.session: ActiveViewSession | None = None
        self.proposal_id: str | None = None

    def _state_event(self) -> dict[str, Any]:
        if self.session is None:
            return {
                "type": "active_view_state",
                "phase": ActiveViewPhase.IDLE.value,
                "session_id": None,
                "identity_id": None,
                "proposal_id": None,
                "request_id": None,
                "evidence_ids": list(self.evidence_ids),
                "reasons": [],
                **_coordinator_event_base(),
            }
        return {
            "type": "active_view_state",
            "phase": self.session.phase.value,
            "session_id": self.session.session_id,
            "identity_id": self.session.identity_id,
            "proposal_id": self.proposal_id,
            "request_id": self.session.request_id,
            "evidence_ids": list(self.session.evidence_ids),
            "reasons": list(self.session.reasons),
            "updated_ns": self.session.updated_ns,
            **_coordinator_event_base(),
        }

    def _rejected(self, reason: str) -> dict[str, Any]:
        return {
            "type": "active_view_protocol_rejected",
            "reason": reason,
            "session_id": None if self.session is None else self.session.session_id,
            **_coordinator_event_base(),
        }

    def _abort(self, reason: str, now_ns: int) -> list[dict[str, Any]]:
        if self.session is None or self.session.phase in {
            ActiveViewPhase.ABORTED,
            ActiveViewPhase.COMPLETE,
        }:
            return [self._rejected(reason)]
        self.session = self.session.transition(
            Cancel(self.session.session_id, reason, max(now_ns, self.session.updated_ns + 1)),
            self.config,
        )
        self.proposal_id = None
        return [self._state_event()]

    def expire_evidence(self, evidence_id: str, *, now_ns: int) -> list[dict[str, Any]]:
        """Fail closed when evidence bound to the current session is invalidated."""

        if self.session is None:
            return [self._rejected("session_unavailable")]
        try:
            validated = validated_evidence_ids((evidence_id,))[0]
        except InvalidDataError:
            return [self._rejected("evidence_not_bound")]
        if validated not in self.session.evidence_ids:
            return [self._rejected("evidence_not_bound")]
        if self.session.phase in {ActiveViewPhase.ABORTED, ActiveViewPhase.COMPLETE}:
            return [self._rejected("evidence_expired")]
        self.session = self.session.transition(
            EvidenceExpired(
                self.session.session_id,
                validated,
                max(now_ns, self.session.updated_ns + 1),
            ),
            self.config,
        )
        self.proposal_id = None
        return [self._state_event()]

    def handle_command(
        self,
        command: Mapping[str, Any],
        *,
        now_ns: int,
    ) -> list[dict[str, Any]]:
        if not isinstance(command, Mapping):
            return [self._rejected("command_invalid")]
        command_type = command.get("type")
        if command_type == "active_view_start":
            if set(command) != {"type", "session_id", "identity_id"}:
                return [self._rejected("command_keys_invalid")]
            try:
                session_id = _uuid(command["session_id"], "session_id")
                identity_id = _identity_id(command["identity_id"])
            except InvalidDataError:
                return [self._rejected("command_id_invalid")]
            if self.session is not None and self.session.phase not in {
                ActiveViewPhase.ABORTED,
                ActiveViewPhase.COMPLETE,
            }:
                return [self._rejected("session_already_active")]
            self.session = ActiveViewSession.start(
                session_id,
                identity_id,
                self.evidence_ids,
                now_ns,
            )
            self.proposal_id = None
            return [self._state_event()]

        if self.session is None:
            return [self._rejected("session_unavailable")]
        if command.get("session_id") != self.session.session_id:
            return [self._rejected("session_mismatch")]
        try:
            if command_type == "active_view_operator_confirmed":
                if set(command) != {"type", "session_id", "proposal_id"}:
                    return [self._rejected("command_keys_invalid")]
                proposal_id = _uuid(command["proposal_id"], "proposal_id")
                if proposal_id != self.proposal_id:
                    return self._abort("proposal_not_pending", now_ns)
                self.session = self.session.transition(
                    OperatorConfirmed(self.session.session_id, proposal_id, now_ns),
                    self.config,
                )
            elif command_type == "active_view_motion_started":
                if set(command) != {"type", "session_id", "proposal_id", "request_id"}:
                    return [self._rejected("command_keys_invalid")]
                proposal_id = _uuid(command["proposal_id"], "proposal_id")
                request_id = _uuid(command["request_id"], "request_id")
                if proposal_id != self.proposal_id:
                    return self._abort("proposal_not_pending", now_ns)
                self.session = self.session.transition(
                    MoveStarted(self.session.session_id, request_id, now_ns),
                    self.config,
                )
            elif command_type == "active_view_motion_completed":
                if set(command) != {"type", "session_id", "request_id"}:
                    return [self._rejected("command_keys_invalid")]
                request_id = _uuid(command["request_id"], "request_id")
                self.session = self.session.transition(
                    MoveCompleted(self.session.session_id, request_id, now_ns),
                    self.config,
                )
                self.proposal_id = None
            elif command_type == "active_view_motion_failed":
                if set(command) != {"type", "session_id", "request_id", "reason"}:
                    return [self._rejected("command_keys_invalid")]
                _uuid(command["request_id"], "request_id")
                reason = command["reason"]
                if not isinstance(reason, str) or not reason or len(reason) > 128:
                    return [self._rejected("failure_reason_invalid")]
                return self._abort(f"motion_failed:{reason}", now_ns)
            elif command_type == "active_view_cancel":
                if set(command) != {"type", "session_id"}:
                    return [self._rejected("command_keys_invalid")]
                return self._abort("operator_cancelled", now_ns)
            else:
                return [self._rejected("command_type_invalid")]
        except (InvalidDataError, InvalidTransition):
            return self._abort("protocol_transition_invalid", now_ns)
        return [self._state_event()]

    def offer_proposal(
        self,
        proposal: ObservationMoveProposal,
        *,
        now_ns: int,
    ) -> list[dict[str, Any]]:
        if self.session is None:
            return [self._rejected("session_unavailable")]
        if proposal.identity_id != self.session.identity_id:
            return self._abort("target_identity_changed", now_ns)
        try:
            self.session = self.session.transition(
                ProposalReady(self.session.session_id, proposal),
                self.config,
            )
        except InvalidTransition:
            return self._abort("proposal_transition_invalid", now_ns)
        if self.session.phase is ActiveViewPhase.ABORTED or proposal.kind == "none":
            self.proposal_id = None
            return [self._state_event()]
        proposal_id = _uuid(self.proposal_id_factory(), "proposal_id")
        self.proposal_id = proposal_id
        event = {
            "type": "active_view_move_proposal",
            "session_id": self.session.session_id,
            "proposal_id": proposal_id,
            "identity_id": proposal.identity_id,
            "kind": proposal.kind,
            "source_frame_id": proposal.source_stamp.frame_id,
            "source_monotonic_ns": proposal.source_stamp.monotonic_ns,
            "expires_ns": proposal.expires_ns,
            "target_pose_id": proposal.target_pose_id,
            "joints_deg": None if proposal.joints_deg is None else proposal.joints_deg.tolist(),
            "delta_base_m": None
            if proposal.delta_base_m is None
            else proposal.delta_base_m.tolist(),
            "optical_axis_base": None
            if proposal.optical_axis_base is None
            else proposal.optical_axis_base.tolist(),
            "rotation_delta_rad": None
            if proposal.rotation_delta_rad is None
            else proposal.rotation_delta_rad.tolist(),
            "evidence_ids": list(proposal.evidence_ids),
            **_coordinator_event_base(),
        }
        return [event, self._state_event()]


__all__ = [
    "ActiveViewPhase",
    "ActiveViewSession",
    "ActiveViewSessionCoordinator",
    "Cancel",
    "DepthObserved",
    "DepthStabilityDecision",
    "DepthStabilityWindow",
    "EvidenceExpired",
    "IdentityObserved",
    "InvalidTransition",
    "LockTarget",
    "MoveCompleted",
    "MoveStarted",
    "OperatorConfirmed",
    "ProposalReady",
    "Settled",
]
