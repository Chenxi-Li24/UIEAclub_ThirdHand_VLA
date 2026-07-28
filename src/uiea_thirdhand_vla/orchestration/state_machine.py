"""
Core state machine engine  deterministic FSM with validated transitions.

States: IDLE -> DETECT -> APPROACH -> GRASP -> LIFT -> TRANSFER -> PLACE -> RETURN -> SUCCESS
Error states: ERROR (recoverable), EMERGENCY_STOP (manual reset required)
"""

from enum import Enum, auto
from dataclasses import dataclass, field
from ..utils.errors import IllegalTransition


class State(Enum):
    IDLE = auto()
    DETECT = auto()
    APPROACH = auto()
    GRASP = auto()
    LIFT = auto()
    TRANSFER = auto()
    PLACE = auto()
    RETURN = auto()
    SUCCESS = auto()
    ERROR = auto()
    EMERGENCY_STOP = auto()


@dataclass
class StateContext:
    """Mutable context passed through state machine transitions."""
    target_id: int | str | None = None
    target_pixel: tuple | None = None
    target_base_pose: tuple | None = None
    grasp_pose: tuple | None = None
    place_pose: tuple | None = None
    detections: list = field(default_factory=list)


class StateMachine:
    """Deterministic FSM for task execution."""

    _transitions = {
        State.IDLE:       [State.DETECT, State.ERROR],
        State.DETECT:     [State.APPROACH, State.ERROR],
        State.APPROACH:   [State.GRASP, State.DETECT, State.ERROR],
        State.GRASP:      [State.LIFT, State.ERROR],
        State.LIFT:       [State.TRANSFER, State.ERROR],
        State.TRANSFER:   [State.PLACE, State.ERROR],
        State.PLACE:      [State.RETURN, State.ERROR],
        State.RETURN:     [State.SUCCESS, State.ERROR],
        State.SUCCESS:    [State.IDLE],
        State.ERROR:      [State.IDLE, State.RETURN],
        State.EMERGENCY_STOP: [State.IDLE],
    }

    def __init__(self, ccu, task_config):
        self.ccu = ccu
        self.state = State.IDLE
        self.ctx = StateContext()

    def transition(self, to: State):
        if to not in self._transitions[self.state]:
            raise IllegalTransition(
                f"Cannot transition {self.state.name} -> {to.name}"
            )
        self.state = to

    def run(self):
        """Blocking execution loop."""
        pass  # TODO: implement state handlers
