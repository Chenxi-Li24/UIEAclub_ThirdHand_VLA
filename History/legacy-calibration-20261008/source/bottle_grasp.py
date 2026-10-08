"""
Bottle grasp — YOLO detection + Startouch SDK Cartesian move.
  python bottle_grasp.py              # Detect + move
  python bottle_grasp.py --dry-run    # Detect only, no arm movement
  python bottle_grasp.py --approach   # Move above bottle, don't grasp
"""
import sys, os, time, json, requests, numpy as np
import argparse

sys.path.insert(0, '/home/nieqingcao/arm/startouch_sdk/interface_py')
from startouchclass import SingleArm

# ============================================================
YOLO_URL = "http://localhost:8088/objects"
CAN_IF = "can0"

# Motion params
SAFE_Z_OFFSET = 0.12   # Approach height above desk (m)
GRASP_Z = 0.01         # Grasp height — just above desk (m)
LIFT_Z = 0.15          # Lift height after grasp (m)
PLACE_X = 0.20         # Place X
PLACE_Y = 0.0          # Place Y
TIME_SEC = 3.0         # Move duration
SPEED = 0.15           # Speed fraction
GRIPPER_CLOSE = 0.02   # Gripper close distance (m)
GRIPPER_OPEN = 0.06    # Gripper open distance (m)
# ============================================================


def detect_bottle():
    """Get bottle position from YOLO server."""
    try:
        r = requests.get(YOLO_URL, timeout=5)
        data = r.json()
        bottles = [o for o in data.get('objects', []) if o['label'] == 'bottle']
        if not bottles:
            # Fallback: take first object
            bottles = data.get('objects', [])
        return bottles
    except Exception as e:
        print(f"Detection error: {e}")
        return []


def grasp_sequence(arm, target, dry_run=False):
    """Execute grasp sequence: approach → descend → grasp → lift → place."""
    bx = float(target['bx'])
    by = float(target['by'])

    # Get current orientation from arm (or use defaults for dry run)
    if arm is not None:
        pos, euler = arm.get_ee_pose_euler()
        roll, pitch, yaw = euler[0], euler[1], euler[2]
        print(f"  Current TCP: ({pos[0]:.4f}, {pos[1]:.4f}, {pos[2]:.4f})")
    else:
        roll, pitch, yaw = 3.14, 0.0, 0.0  # Default: pointing down

    # Build waypoints
    approach_pose = [bx, by, SAFE_Z_OFFSET, roll, pitch, yaw]
    grasp_pose = [bx, by, GRASP_Z, roll, pitch, yaw]
    lift_pose = [bx, by, LIFT_Z, roll, pitch, yaw]
    place_pose = [PLACE_X, PLACE_Y, LIFT_Z, roll, pitch, yaw]
    place_down = [PLACE_X, PLACE_Y, GRASP_Z, roll, pitch, yaw]

    poses = [approach_pose, grasp_pose, lift_pose, place_pose, place_down]

    print(f"\n  Target: bottle at ({bx:.4f}, {by:.4f})")
    print(f"  Orientation: roll={roll:.2f} pitch={pitch:.2f} yaw={yaw:.2f}")
    print(f"  Waypoints:")
    for i, p in enumerate(poses):
        print(f"    {i+1}. [{p[0]:.4f}, {p[1]:.4f}, {p[2]:.4f}]")

    if dry_run:
        print("\n  [DRY RUN] Would execute:")
        print(f"  1. Open gripper → 2. Approach → 3. Grasp → 4. Close → 5. Lift → 6. Place → 7. Open")
        return True

    # Execute
    try:
        # Open gripper first
        arm.setGripperDistance(GRIPPER_OPEN)
        time.sleep(0.5)

        # Move to approach
        print("  1. Moving to approach...")
        arm.move_l([approach_pose], time_sec=TIME_SEC, blend_radius_m=0.0,
                   position_tolerance_m=0.005, orientation_tolerance_rad=0.05)

        # Move to grasp (slower)
        print("  2. Descending to grasp...")
        arm.move_l([grasp_pose], time_sec=TIME_SEC * 1.5, blend_radius_m=0.0,
                   position_tolerance_m=0.003, orientation_tolerance_rad=0.05)

        # Close gripper
        print("  3. Closing gripper...")
        arm.setGripperDistance(GRIPPER_CLOSE)
        time.sleep(1.0)

        # Lift
        print("  4. Lifting...")
        arm.move_l([lift_pose], time_sec=TIME_SEC, blend_radius_m=0.0,
                   position_tolerance_m=0.005, orientation_tolerance_rad=0.05)

        # Move to place
        print("  5. Moving to place...")
        arm.move_l([place_pose, place_down], time_sec=TIME_SEC * 2, blend_radius_m=0.02,
                   position_tolerance_m=0.005, orientation_tolerance_rad=0.05)

        # Open gripper
        print("  6. Releasing...")
        arm.setGripperDistance(GRIPPER_OPEN)
        time.sleep(0.5)

        # Back to safe height
        arm.move_l([place_pose], time_sec=TIME_SEC,
                   position_tolerance_m=0.005, orientation_tolerance_rad=0.05)

        print("\n✅ Grasp complete!")
        return True

    except Exception as e:
        print(f"\n❌ Grasp failed: {e}")
        arm.setGripperDistance(GRIPPER_OPEN)
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true', help='Detect only, no movement')
    parser.add_argument('--approach', action='store_true', help='Move above bottle, no grasp')
    args = parser.parse_args()

    # 1. Detect
    print("[1/3] Detecting bottle...")
    bottles = detect_bottle()

    if not bottles:
        print("  No bottle found! Make sure YOLO server :8088 is running.")
        print("  Start it: python3 /home/nieqingcao/calibration/visual_grasp.py")
        return

    target = bottles[0]
    print(f"  Found: {target['label']} at ({target['bx']}, {target['by']})m, conf={target['conf']}")

    if args.dry_run:
        grasp_sequence(None, target, dry_run=True)
        return

    # 2. Connect arm
    print("\n[2/3] Connecting to arm...")
    arm = SingleArm(can_interface_=CAN_IF, enable_fd_=False)

    try:
        time.sleep(0.3)
        pos, _ = arm.get_ee_pose_euler()
        print(f"  Connected. TCP: ({pos[0]:.4f}, {pos[1]:.4f}, {pos[2]:.4f})")

        # 3. Execute
        print(f"\n[3/3] Executing grasp{' (approach only)' if args.approach else ''}...")
        grasp_sequence(arm, target, dry_run=False)

    finally:
        arm.cleanup()
        print("Arm disconnected.")


if __name__ == '__main__':
    main()
