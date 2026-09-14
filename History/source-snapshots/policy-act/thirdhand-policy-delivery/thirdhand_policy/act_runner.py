"""
LeRobot ACT checkpoint loader and inference boundary.

This module is imported lazily by :mod:`thirdhand_policy.policies` so the Policy
service can run ``fixed_baseline`` and ``fake_act`` without torch/lerobot. When
``lerobot_act`` is requested, this module must be able to import torch + lerobot
on the host, load the checkpoint directory produced by the ACT training pipeline,
and convert the resulting action chunk into contract ``actionStep`` dicts.

The observation space is fixed by the technical plan (``ThirdHand Coke Bottle
Skill Complete Guide``, section 6.3)::

    observation.images.ego_rgb      [3, H, W]   # RGB from the Lumos Ego
    observation.images.target_mask  [3, H, W]   # authorized binary mask, 3-ch uint8
    observation.state               [7]         # 6 joint positions (rad) + gripper
    action                          [7]         # same layout as state

Checkpoint layout (produced by the ACT training pipeline)::

    <checkpoint_dir>/
        config.yaml      # LeRobot ACT policy config
        policy.pth       # torch state_dict

The action space is ``startouch-j1-j6-rad-gripper-v1`` (J1..J6 in radians +
gripper ``0=closed 1=open``). A checkpoint whose feature order, image keys or
action space do not match is rejected rather than silently reused.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from . import messages
from .policies import PolicyError

#: Expected state/action dimensionality for startouch-j1-j6-rad-gripper-v1.
STATE_DIM = 7  # [J1..J6 (rad), gripperNormalized]

#: Contract feature names (the two image features + state).
OBS_EGO_RGB = "observation.images.ego_rgb"
OBS_TARGET_MASK = "observation.images.target_mask"
OBS_STATE = "observation.state"
REQUIRED_IMAGE_KEYS = (OBS_EGO_RGB, OBS_TARGET_MASK)


def run_action_chunk(*, checkpoint: str, payload: dict[str, Any], config: dict[str, Any]) -> list[dict]:
    """Load the ACT policy and return a list of ``actionStep`` dicts."""
    try:
        import torch
    except ImportError as exc:
        raise PolicyError("lerobot_unavailable", f"torch unavailable: {exc}") from exc

    checkpoint_path = Path(checkpoint)
    if not (checkpoint_path / "policy.pth").exists():
        raise PolicyError(
            "checkpoint_missing",
            f"checkpoint dir must contain policy.pth: {checkpoint_path}",
        )

    policy = _load_policy(checkpoint_path, device=config.get("device", "cpu"))

    # Resolve the observation (ego_rgb + target_mask + state) from the artifact
    # store referenced by the request's frameId / maskRef / robotStateRef.
    observation = _resolve_observation(payload, config)
    if observation is None:
        raise PolicyError(
            "observation_unresolved",
            "cannot resolve frameId/maskRef/robotStateRef from the artifact store",
        )

    with torch.inference_mode():
        chunk = policy.predict(observation)

    dt_ms = int(config.get("dt_ms", 100))
    return _chunk_to_steps(chunk, dt_ms=dt_ms)


def _load_policy(checkpoint_path: Path, *, device: str):
    """Load a LeRobot ACT policy from a checkpoint directory, validating its
    feature structure against the frozen observation/action space."""
    try:
        from lerobot.common.policies.factory import make_policy
        from omegaconf import OmegaConf
    except ImportError as exc:
        raise PolicyError("lerobot_unavailable", f"lerobot unavailable: {exc}") from exc

    import torch

    cfg = OmegaConf.load(checkpoint_path / "config.yaml")

    # Reject a checkpoint trained for a different action space or feature order.
    state_dim = _infer_state_dim(cfg)
    if state_dim is not None and state_dim != STATE_DIM:
        raise PolicyError(
            "incompatible_action_space",
            f"checkpoint state dim {state_dim} != {STATE_DIM} (startouch-j1-j6-rad-gripper-v1)",
        )
    image_keys = _infer_image_keys(cfg)
    if image_keys is not None and not set(REQUIRED_IMAGE_KEYS) <= set(image_keys):
        raise PolicyError(
            "incompatible_observation_space",
            f"checkpoint image features {image_keys} missing required {list(REQUIRED_IMAGE_KEYS)}",
        )

    policy = make_policy(cfg)
    policy.load_state_dict(torch.load(checkpoint_path / "policy.pth", map_location=device))
    policy.to(device).eval()
    return policy


def _infer_state_dim(cfg) -> int | None:
    """Best-effort: read the action/state dim from the LeRobot config."""
    if not hasattr(cfg, "policy"):
        return None
    for key in ("output_shapes", "input_shapes"):
        shapes = getattr(cfg.policy, key, None)
        if not shapes:
            continue
        for feature in ("action", "observation.state"):
            value = shapes.get(feature)
            if value:
                text = str(value).strip("[]")
                parts = text.split(",")
                if len(parts) == 1 and parts[0].strip().isdigit():
                    return int(parts[0].strip())
    return None


def _infer_image_keys(cfg) -> list[str] | None:
    """Best-effort: read the image feature keys from the LeRobot config."""
    if not hasattr(cfg, "observation_features"):
        return None
    keys = list(getattr(cfg, "observation_features", {}).keys())
    return [key for key in keys if key.startswith("observation.images.")]


def _resolve_observation(payload: dict[str, Any], config: dict[str, Any]) -> dict[str, Any] | None:
    """Resolve (ego_rgb, target_mask, state) from the artifact store.

    The artifact store keeps observation tensors keyed by the references carried
    in the JSON contract, so no image/mask/state bytes travel in messages::

        <artifact_dir>/frames/<frameId>.npz       -> {"image": (H,W,3) uint8}
        <artifact_dir>/masks/<maskRef>.npz        -> {"mask":  (H,W,3) uint8}
        <artifact_dir>/states/<robotStateRef>.npz -> {"state": (7,) float32}

    Returns ``None`` when any reference cannot be resolved (the handler then
    reports failure rather than guessing missing data).
    """
    artifact_dir = config.get("artifact_dir")
    if not artifact_dir:
        return None
    root = Path(artifact_dir)
    target = payload.get("target") or {}
    frame_id = target.get("frameId")
    mask_ref = target.get("maskRef")
    state_ref = payload.get("robotStateRef")
    if not frame_id or not mask_ref or not state_ref:
        return None

    frame_path = root / "frames" / f"{frame_id}.npz"
    mask_path = root / "masks" / f"{mask_ref}.npz"
    state_path = root / "states" / f"{state_ref}.npz"
    if not frame_path.exists() or not mask_path.exists() or not state_path.exists():
        return None

    return {
        OBS_EGO_RGB: np.load(frame_path)["image"],
        OBS_TARGET_MASK: np.load(mask_path)["mask"],
        OBS_STATE: np.load(state_path)["state"],
    }


def _chunk_to_steps(chunk, *, dt_ms: int) -> list[dict]:
    """Convert an ACT chunk ``(n_steps, 7)`` into contract ``actionStep`` dicts."""
    array = np.asarray(chunk, dtype=np.float64)
    if array.ndim == 3:
        array = array[0]
    steps = []
    for row in array:
        joints_rad = row[: messages.JOINT_COUNT]
        gripper = float(row[messages.JOINT_COUNT])
        steps.append(messages.make_action_step(dt_ms, joints_rad, gripper))
    return steps
