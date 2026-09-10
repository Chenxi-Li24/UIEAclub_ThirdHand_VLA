"""
Core state machine engine — deterministic FSM for pick-and-place tasks.

States: IDLE → DETECT → APPROACH → GRASP → LIFT → TRANSFER → PLACE → RETURN → SUCCESS
VLA integration: optionally calls cloud VLA at DETECT state when multiple objects found.
"""

import logging
import time
from dataclasses import dataclass, field
from enum import Enum, auto

from uiea_thirdhand_vla.utils.errors import IllegalTransition
from uiea_thirdhand_vla.utils.types import Detection

logger = logging.getLogger(__name__)


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
    vla_recommendation: object = None
    error_message: str = ""
    cycle_count: int = 0


class StateMachine:
    """Deterministic FSM with optional VLA integration for pick-and-place."""

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

    def __init__(self, ccu, task_config=None):
        """
        Args:
            ccu: CentralControlUnit with robot, camera, detector, gripper, safety, logger
            task_config: TaskConfig or dict with task parameters
        """
        self.ccu = ccu
        self.config = task_config or {}
        self.state = State.IDLE
        self.ctx = StateContext()
        self._running = False
        self._vla_client = None  # Lazy-init

        # Task parameters
        self._approach_height = 0.08   # m above object before grasp
        self._lift_height = 0.15       # m lift after grasp
        self._place_height = 0.05      # m above place location
        self._gripper_close_pos = 0.02  # closed position (m)
        self._gripper_open_pos = 0.06   # open position (m)

    # ---- State transition ----

    def transition(self, to: State):
        """Validate and execute state transition."""
        if to not in self._transitions.get(self.state, []):
            raise IllegalTransition(
                f"Cannot transition {self.state.name} → {to.name}"
            )
        old = self.state
        self.state = to
        logger.info(f"State: {old.name} → {to.name}")

    # ---- Main loop ----

    def run(self, max_cycles: int = 0):
        """Blocking execution loop. Set max_cycles > 0 for auto-stop."""
        self._running = True
        self.state = State.IDLE

        try:
            while self._running:
                if max_cycles > 0 and self.ctx.cycle_count >= max_cycles:
                    logger.info(f"Max cycles ({max_cycles}) reached")
                    break

                handler = self._handlers.get(self.state)
                if handler:
                    handler()
                else:
                    logger.warning(f"No handler for state {self.state.name}")
                    time.sleep(0.1)

                if self.state == State.SUCCESS:
                    self.ctx.cycle_count += 1
                    logger.info(f"Cycle {self.ctx.cycle_count} complete")
                    if max_cycles > 0 and self.ctx.cycle_count >= max_cycles:
                        break
                    self.transition(State.IDLE)

        except KeyboardInterrupt:
            logger.info("Interrupted by user")
            self.state = State.ERROR
        except Exception as e:
            logger.error(f"State machine error: {e}")
            self.ctx.error_message = str(e)
            self.state = State.ERROR
        finally:
            self._running = False

    def stop(self):
        """Graceful stop."""
        self._running = False

    # ---- State handlers ----

    @property
    def _handlers(self):
        return {
            State.IDLE: self._handle_idle,
            State.DETECT: self._handle_detect,
            State.APPROACH: self._handle_approach,
            State.GRASP: self._handle_grasp,
            State.LIFT: self._handle_lift,
            State.TRANSFER: self._handle_transfer,
            State.PLACE: self._handle_place,
            State.RETURN: self._handle_return,
            State.SUCCESS: self._handle_success,
            State.ERROR: self._handle_error,
        }

    def _handle_idle(self):
        """Wait for start signal, then transition to DETECT."""
        logger.debug("IDLE: waiting for start...")
        time.sleep(0.5)
        # Auto-start for now — in production, wait for user/trigger
        self.transition(State.DETECT)

    def _handle_detect(self):
        """Capture frame, run detection, decide next action."""
        logger.debug("DETECT: capturing frame...")

        # Capture
        frame = self.ccu.camera.capture()
        if frame is None:
            self.transition(State.ERROR)
            self.ctx.error_message = "Camera capture failed"
            return

        # Detect
        detections = self.ccu.detector.detect(frame)
        self.ctx.detections = detections

        if not detections:
            logger.info("DETECT: no objects found")
            time.sleep(0.5)
            return  # Stay in DETECT, retry

        logger.info(f"DETECT: found {len(detections)} objects: "
                    f"{[d.label for d in detections]}")

        # If multiple objects and VLA is available, ask it to choose
        if len(detections) > 1 and self._vla_client is not None:
            try:
                context = {
                    "task": "pick_and_place",
                    "detections": detections,
                }
                rec = self._vla_client.reason_sync(frame, context)
                self.ctx.vla_recommendation = rec
                logger.info(f"VLA recommends: {rec.action} → {rec.target_label}")

                # Select the VLA's chosen target
                target_label = rec.target_label
                for d in detections:
                    if d.label == target_label or str(d.id) == target_label:
                        self._select_target(d)
                        break
                else:
                    # VLA selection not found — pick first
                    self._select_target(detections[0])
            except Exception as e:
                logger.warning(f"VLA call failed: {e}, using first detection")
                self._select_target(detections[0])
        else:
            # Single object or no VLA — pick first
            self._select_target(detections[0])

        self.transition(State.APPROACH)

    def _select_target(self, detection: Detection):
        """Set the current target from detection."""
        self.ctx.target_id = detection.id
        self.ctx.target_pixel = detection.center_pixel

        if detection.pose_base is not None:
            self.ctx.target_base_pose = detection.pose_base.position
        elif detection.pose_camera is not None:
            # Convert camera pose to base
            point_base = self.ccu.transforms.camera_to_base(
                list(detection.pose_camera.position)
            )
            self.ctx.target_base_pose = tuple(point_base)
        else:
            # Fallback: use pixel + desktop plane
            if self.ccu.transforms.H_desktop is not None:
                x, y = self.ccu.transforms.pixel_to_base_homography(
                    *detection.center_pixel
                )
                self.ctx.target_base_pose = (x, y, 0.0)
            else:
                logger.warning("No coordinate transform available!")
                self.ctx.target_base_pose = (0.0, 0.0, 0.05)

        logger.info(f"Target: id={self.ctx.target_id}, "
                    f"base_pose={self.ctx.target_base_pose}")

    def _handle_approach(self):
        """Move to pre-grasp position above target."""
        logger.debug("APPROACH: moving to pre-grasp...")

        if self.ctx.target_base_pose is None:
            self.transition(State.DETECT)
            return

        tx, ty, tz = self.ctx.target_base_pose
        # Move to approach position (above target)
        approach_pose = (tx, ty, tz + self._approach_height, 0, 0, 0)

        try:
            self.ccu.move_to_pose(approach_pose, speed=0.15)
            time.sleep(0.5)
            # Open gripper before grasp
            self.ccu.gripper.open(self._gripper_open_pos)
            time.sleep(0.3)
            self.transition(State.GRASP)
        except Exception as e:
            logger.error(f"APPROACH failed: {e}")
            self.ctx.error_message = str(e)
            self.transition(State.ERROR)

    def _handle_grasp(self):
        """Descend to target and close gripper."""
        logger.debug("GRASP: descending to target...")

        if self.ctx.target_base_pose is None:
            self.transition(State.DETECT)
            return

        tx, ty, tz = self.ctx.target_base_pose
        grasp_pose = (tx, ty, tz + 0.005, 0, 0, 0)  # slight Z offset

        try:
            self.ccu.move_to_pose(grasp_pose, speed=0.08)
            time.sleep(0.3)
            self.ccu.gripper.close(self._gripper_close_pos)
            time.sleep(0.5)
            self.transition(State.LIFT)
        except Exception as e:
            logger.error(f"GRASP failed: {e}")
            self.ctx.error_message = str(e)
            self.transition(State.ERROR)

    def _handle_lift(self):
        """Lift object above workspace."""
        logger.debug("LIFT: raising object...")
        if self.ctx.target_base_pose is None:
            self.transition(State.DETECT)
            return

        try:
            tx, ty, tz = self.ctx.target_base_pose
            lift_pose = (tx, ty, tz + self._lift_height, 0, 0, 0)
            self.ccu.move_to_pose(lift_pose, speed=0.12)
            time.sleep(0.5)
            self.transition(State.TRANSFER)
        except Exception as e:
            logger.error(f"LIFT failed: {e}")
            self.ctx.error_message = str(e)
            self.transition(State.ERROR)

    def _handle_transfer(self):
        """Move to place location."""
        logger.debug("TRANSFER: moving to place location...")

        place_pose = self.ctx.place_pose or (0.15, 0.0, self._place_height, 0, 0, 0)
        try:
            self.ccu.move_to_pose(place_pose, speed=0.15)
            time.sleep(0.5)
            self.transition(State.PLACE)
        except Exception as e:
            logger.error(f"TRANSFER failed: {e}")
            self.ctx.error_message = str(e)
            self.transition(State.ERROR)

    def _handle_place(self):
        """Place object and release gripper."""
        logger.debug("PLACE: releasing object...")

        place_pose = self.ctx.place_pose or (0.15, 0.0, 0.01, 0, 0, 0)
        try:
            self.ccu.move_to_pose(place_pose, speed=0.08)
            time.sleep(0.3)
            self.ccu.gripper.open(self._gripper_open_pos)
            time.sleep(0.5)
            self.transition(State.RETURN)
        except Exception as e:
            logger.error(f"PLACE failed: {e}")
            self.ctx.error_message = str(e)
            self.transition(State.ERROR)

    def _handle_return(self):
        """Return to home/neutral position."""
        logger.debug("RETURN: going home...")
        try:
            # Lift gripper first
            place_pos = self.ctx.place_pose or (0.15, 0.0, 0.05)
            lift = (place_pos[0], place_pos[1], self._lift_height, 0, 0, 0)
            self.ccu.move_to_pose(lift, speed=0.15)
            time.sleep(0.5)
            self.transition(State.SUCCESS)
        except Exception as e:
            logger.error(f"RETURN failed: {e}")
            self.ctx.error_message = str(e)
            self.transition(State.ERROR)

    def _handle_success(self):
        """Task completed successfully."""
        logger.info("SUCCESS: task complete!")
        # Stay here until external reset to IDLE

    def _handle_error(self):
        """Handle error state — log and attempt recovery."""
        logger.error(f"ERROR: {self.ctx.error_message}")

        # Try to stop safely
        try:
            self.ccu.gripper.open(self._gripper_open_pos)
        except Exception:
            pass

        # Ask VLA for recovery strategy if available
        if self._vla_client is not None:
            try:
                frame = self.ccu.camera.capture()
                if frame:
                    context = {
                        "task": "error_recovery",
                        "error": self.ctx.error_message,
                        "robot_state": {},
                    }
                    rec = self._vla_client.reason_sync(frame, context)
                    if rec.action == "recover":
                        logger.info(f"VLA recovery: {rec.reasoning}")
                        for step in rec.recovery_steps:
                            logger.info(f"  → {step}")
            except Exception:
                pass

        # Wait for external intervention
        time.sleep(2.0)

    # ---- VLA Integration ----

    def set_vla_client(self, client):
        """Attach a VLA client for cloud reasoning."""
        self._vla_client = client
