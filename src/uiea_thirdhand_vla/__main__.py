"""
ThirdHand VLA — Main entry point.

Usage:
  python -m uiea_thirdhand_vla --mode camera       # Camera test
  python -m uiea_thirdhand_vla --mode detect       # Detection test
  python -m uiea_thirdhand_vla --mode pick_place   # Pick-and-place cycle
  python -m uiea_thirdhand_vla --mode web          # Web console only
  python -m uiea_thirdhand_vla                     # Full system
"""

import argparse
import logging
import threading

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger("vla")


def setup_system(config_path=None):
    """Initialize all subsystems and return CCU + StateMachine."""
    from .config.loader import load_config
    config = load_config(config_path) if config_path else {}

    # 1. Camera + Calibration
    from .perception.calibration import CameraCalibration
    from .perception.camera import Camera
    from .perception.detectors.base import BaseDetector
    from .perception.transforms import CoordinateTransforms

    camera = Camera(config.get("camera", {}))
    calib = CameraCalibration.for_lumos_ego_std()
    camera.set_intrinsics(calib)

    transforms = CoordinateTransforms(
        camera_matrix=calib.K,
        seucm_params=calib.seucm_params,
        desktop_z=0.0,
    )

    # 2. Detector (ArUco by default)
    detector_type = config.get("task", {}).get("detector_type", "aruco")
    detector: BaseDetector
    if detector_type == "yolo":
        from .perception.detectors.yolo_detector import YoloDetector
        detector = YoloDetector(
            model_path=config.get("yolo", {}).get("model", "yolov8n.pt"),
            transforms=transforms,
        )
    else:
        from .perception.detectors.aruco_detector import ArucoDetector
        detector = ArucoDetector(
            dictionary="DICT_4X4_50", marker_size_m=0.05,
            transforms=transforms,
        )
    detector.set_camera_matrix(calib.K)

    # 3. Robot + Gripper + Safety
    from .control.gripper import Gripper
    from .control.robot import Robot
    from .control.safety import Safety
    robot = Robot(config.get("robot", {}))
    gripper = Gripper()
    safety = Safety(config.get("robot", {}))

    # 4. Logger
    from .logging.run_logger import RunLogger
    run_logger = RunLogger()

    # 5. CCU
    from .orchestration.central_control import CentralControlUnit
    ccu = CentralControlUnit(robot, camera, detector, gripper, safety,
                             transforms, run_logger)

    # 6. VLA Client (optional)
    vla_client = None
    vla_cfg = config.get("vla", {})
    if vla_cfg.get("provider"):
        from .reasoning.vla_client import VLAClient
        vla_client = VLAClient(vla_cfg)
        logger.info(f"VLA: {vla_cfg['provider']}/{vla_cfg.get('model','?')}")

    # 7. State Machine
    from .orchestration.state_machine import StateMachine
    sm = StateMachine(ccu, config.get("task", {}))
    if vla_client:
        sm.set_vla_client(vla_client)

    return ccu, sm, camera, detector


# ---- Mode runners ----

def mode_camera():
    """Camera capture test."""
    import cv2

    from .perception.camera import Camera
    cam = Camera()
    if not cam.open():
        print("Camera open failed")
        return
    print("Camera OK. Press 'q' to quit.")
    while True:
        frame = cam.capture()
        if frame is not None:
            cv2.imshow("Camera", cv2.resize(frame, (640, 640)))
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
    cam.close()
    cv2.destroyAllWindows()


def mode_detect():
    """Detection test with live camera."""
    import cv2

    from .perception.calibration import CameraCalibration
    from .perception.camera import Camera
    from .perception.detectors.aruco_detector import ArucoDetector

    cam = Camera()
    calib = CameraCalibration.for_lumos_ego_std()
    cam.set_intrinsics(calib)
    cam.open()

    detector = ArucoDetector(marker_size_m=0.05)
    detector.set_camera_matrix(calib.K)

    print("Detection test. Press 'q' to quit.")
    while True:
        frame = cam.capture()
        if frame is None:
            continue
        detections = detector.detect(frame)
        out = detector.draw(frame, detections)
        for d in detections:
            if d.pose_camera:
                p = d.pose_camera.position
                print(f"\rID:{d.id} pos=({p[0]:.3f},{p[1]:.3f},{p[2]:.3f})m", end="")
        cv2.imshow("Detection", cv2.resize(out, (640, 640)))
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
    cam.close()
    cv2.destroyAllWindows()


def mode_pick_place():
    """Single pick-and-place cycle."""
    ccu, sm, cam, _ = setup_system()
    if not cam.open():
        print("Camera open failed")
        return
    try:
        sm.run(max_cycles=1)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        cam.close()


def mode_web():
    """Web console only."""
    import uvicorn

    from .web.server import app
    uvicorn.run(app, host="0.0.0.0", port=8000)


# ---- CLI ----

def main():
    parser = argparse.ArgumentParser(description="ThirdHand VLA")
    parser.add_argument("--mode", default="full",
                        choices=["camera", "detect", "pick_place", "web", "full"])
    parser.add_argument("--config", help="YAML config path")
    args = parser.parse_args()

    logger.info(f"ThirdHand VLA — mode={args.mode}")

    modes = {
        "camera": mode_camera,
        "detect": mode_detect,
        "pick_place": mode_pick_place,
        "web": mode_web,
    }

    if args.mode == "full":
        ccu, sm, cam, _ = setup_system(args.config)
        if not cam.open():
            logger.error("Camera failed, running web-only")
        else:
            logger.info("Camera ready")

        import uvicorn

        from .web.server import app
        t = threading.Thread(target=sm.run, daemon=True)
        t.start()
        uvicorn.run(app, host="0.0.0.0", port=8000)
    elif args.mode in modes:
        modes[args.mode]()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
