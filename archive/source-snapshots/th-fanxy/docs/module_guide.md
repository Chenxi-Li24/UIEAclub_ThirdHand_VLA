# Module Guide -- Interface Contracts

## Perception
- Camera: open(), capture() -> ndarray, close()
- BaseDetector(ABC): detect(image) -> list[Detection], draw(image, detections), set_camera_matrix(K, dist)

## Control
- RobotController: connect(), get_joint_angles(), get_ee_pose(), move_j(), move_l(), emergency_stop()
- Gripper: open(), close(), get_distance(), is_grasped()
- SafetyMonitor: check_pose_in_workspace(), check_joints_in_limits(), emergency_stop()

## Interaction
- ASREngine: transcribe(audio) -> str
- NLUEngine: parse(text) -> Optional[Intent]
- TTSEngine: speak(text)
- Intent: action, task_name, params

## Orchestration
- StateMachine: IDLE->DETECT->APPROACH->GRASP->LIFT->TRANSFER->PLACE->RETURN->SUCCESS
- CentralControlUnit: facade wrapping all subsystems with safety checks
- BaseTask(ABC): get_state_machine(ccu), get_detector()

## Config
- ConfigLoader: load_app_config() -> AppConfig (Pydantic-validated)
- AppConfig: robot, camera, workspace, asr_tts, vla, web

## Web API
| Method | Path | Description |
|--------|------|-------------|
| GET | /api/robot/status | Joint angles, EE pose |
| POST | /api/robot/jog | Jog dx,dy,dz |
| POST | /api/robot/estop | Emergency stop |
| GET | /api/camera/stream | MJPEG video |
| POST | /api/task/start | Start task |
| POST | /api/task/stop | Stop task |
| GET | /api/task/status | Task state |
| WS | /ws | Real-time state, frames |
