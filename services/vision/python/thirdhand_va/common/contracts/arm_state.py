"""Immutable robot-arm observation shared by Action modules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from thirdhand_va.common.errors import ContractError

from ._validation import finite_triplet


@dataclass(frozen=True, slots=True)
class ArmState:
    flange_position_m: tuple[float, float, float]
    flange_euler_rad: tuple[float, float, float]
    stationary: bool
    received_monotonic_ns: int
    stationary_since_monotonic_ns: int = 0
    observed_monotonic_ns: int | None = None
    pose_frame: str = "robot_flange"

    def __post_init__(self) -> None:
        try:
            position = finite_triplet(self.flange_position_m, "flange_position_m")
            euler = finite_triplet(self.flange_euler_rad, "flange_euler_rad")
        except ValueError as error:
            raise ContractError(str(error)) from error
        observed_ns = (
            self.received_monotonic_ns
            if self.observed_monotonic_ns is None
            else self.observed_monotonic_ns
        )
        if (
            not isinstance(self.received_monotonic_ns, int)
            or not isinstance(self.stationary_since_monotonic_ns, int)
            or not isinstance(observed_ns, int)
            or self.received_monotonic_ns < 0
            or self.stationary_since_monotonic_ns < 0
            or observed_ns < 0
            or observed_ns > self.received_monotonic_ns
            or self.stationary_since_monotonic_ns > self.received_monotonic_ns
        ):
            raise ContractError("arm_state timestamps are invalid")
        if self.pose_frame != "robot_flange":
            raise ContractError("arm_state pose_frame must be robot_flange")
        object.__setattr__(self, "flange_position_m", position)
        object.__setattr__(self, "flange_euler_rad", euler)
        object.__setattr__(self, "stationary", self.stationary is True)
        object.__setattr__(self, "observed_monotonic_ns", observed_ns)

    @classmethod
    def from_message(
        cls,
        message: Mapping[str, Any],
        *,
        received_monotonic_ns: int,
        stationary_since_monotonic_ns: int,
    ) -> "ArmState":
        if message.get("type") != "arm_state":
            raise ContractError("expected an arm_state message")
        if message.get("pose_frame") != "robot_flange":
            raise ContractError("arm_state pose_frame must be robot_flange")
        try:
            return cls(
                flange_position_m=message.get("flange_position_m"),  # type: ignore[arg-type]
                flange_euler_rad=message.get("flange_euler_rad"),  # type: ignore[arg-type]
                stationary=message.get("stationary") is True,
                received_monotonic_ns=int(received_monotonic_ns),
                stationary_since_monotonic_ns=int(
                    stationary_since_monotonic_ns
                ),
                observed_monotonic_ns=int(
                    message.get("observed_monotonic_ns", received_monotonic_ns)
                ),
                pose_frame="robot_flange",
            )
        except (TypeError, ValueError) as error:
            if isinstance(error, ContractError):
                raise
            raise ContractError("arm_state pose is invalid") from error


__all__ = ["ArmState"]
