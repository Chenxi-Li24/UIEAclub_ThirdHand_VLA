"""Import the independently produced eye-in-hand result into the VA contract."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from .handeye import HandEyeError, _rigid_transform


class HandEyeImportError(HandEyeError):
    """The source bytes or source calibration contract are not trustworthy."""


def _numerical_summary(payload: dict[str, Any]) -> dict[str, Any]:
    validation = payload.get("validation", {})
    held_out = validation.get("held_out", {})
    gates = validation.get("gates", {})
    metric_names = (
        "translation_rmse_m", "translation_p95_m", "translation_max_m",
        "rotation_rmse_deg", "rotation_p95_deg", "rotation_max_deg",
    )
    gate_names = (
        "held_out_translation_rmse_m_max",
        "held_out_rotation_rmse_deg_max",
        "overall_rectified_reprojection_rmse_px_strictly_below",
    )
    result: dict[str, Any] = {
        "held_out": {name: held_out[name] for name in metric_names if name in held_out}
    }
    selected_gates = {name: gates[name] for name in gate_names if name in gates}
    if selected_gates:
        result["gates"] = selected_gates
    return result


def import_handeye_artifact(
    source_path: Path | str,
    output_path: Path | str,
    *,
    expected_sha256: str,
) -> dict[str, Any]:
    """Create a deterministic, pending-activation v3 artifact.

    The source file is read-only.  Byte identity must be supplied by the caller
    so an accidentally replaced calibration cannot silently enter VA.
    """
    source = Path(source_path)
    raw = source.read_bytes()
    actual_sha256 = hashlib.sha256(raw).hexdigest()
    expected = expected_sha256.removeprefix("sha256:").lower()
    if actual_sha256 != expected:
        raise HandEyeImportError(
            f"source SHA-256 mismatch: expected {expected}, got {actual_sha256}"
        )
    try:
        payload = json.loads(raw)
        if payload.get("calibration_type") != "eye_in_hand":
            raise HandEyeImportError("source is not an eye-in-hand calibration")
        matrix = payload["T_flange_camera"]["matrix_4x4"]
        _rigid_transform(matrix, "T_flange_camera")
        camera = payload["camera"]
        serial = camera["camera_serial"]
        mount_id = payload["camera_mount_id"]
        if not isinstance(serial, str) or not serial.strip():
            raise HandEyeImportError("source camera_serial is invalid")
        if not isinstance(mount_id, str) or not mount_id.strip():
            raise HandEyeImportError("source camera_mount_id is invalid")
    except HandEyeImportError:
        raise
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise HandEyeImportError("source calibration contract is incomplete") from error

    physical = payload.get("physical_validation", {})
    artifact: dict[str, Any] = {
        "schema": "thirdhand-handeye-calibration-v3",
        "source": {
            "filename": source.name,
            "sha256": f"sha256:{actual_sha256}",
            "source_content_id": payload.get("content_id"),
        },
        "robot_state_semantics": "T_base_flange",
        "extrinsic_semantics": "T_flange_camera",
        "T_flange_camera": {"matrix_4x4": matrix},
        "camera": {
            "camera_serial": serial,
            "registration_id": f"xvisio-sdk:{serial}",
            "camera_mount_id": mount_id,
        },
        "selected_method": payload.get("selected_method"),
        "numerically_validated": payload.get("numerically_validated") is True,
        "numerical_validation": _numerical_summary(payload),
        # Import never grants physical truth or enables robot motion.
        "camera_mount_id_activation": False,
        "activated_camera_mount_id": None,
        "approved_for_bottle_grasp": False,
        "physical_validation": {
            "status": "pending",
            "measured_error_m": None,
            "required_3d_point_or_grasp_error_m_max": physical.get(
                "required_3d_point_or_grasp_error_m_max", 0.01
            ),
        },
    }
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return artifact


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Import a T_flange_camera calibration as a locked VA v3 artifact"
    )
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    artifact = import_handeye_artifact(
        args.source,
        args.output,
        expected_sha256=args.expected_sha256,
    )
    print(json.dumps({
        "output": str(args.output.resolve()),
        "schema": artifact["schema"],
        "approved_for_bottle_grasp": artifact["approved_for_bottle_grasp"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
