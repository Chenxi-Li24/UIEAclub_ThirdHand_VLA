"""Tests for the ACT runner's observation resolution and feature binding."""

import numpy as np

from thirdhand_policy.act_runner import (
    OBS_EGO_RGB,
    OBS_STATE,
    OBS_TARGET_MASK,
    _infer_image_keys,
    _resolve_observation,
)


def _payload(frame_id="frame-1", mask_ref="mask-1", state_ref="state-1"):
    return {
        "target": {"frameId": frame_id, "maskRef": mask_ref},
        "robotStateRef": state_ref,
    }


def test_resolve_observation_returns_all_three_features(tmp_path):
    frames = tmp_path / "frames"
    masks = tmp_path / "masks"
    states = tmp_path / "states"
    for d in (frames, masks, states):
        d.mkdir()

    np.savez_compressed(frames / "frame-1.npz", image=np.zeros((8, 8, 3), dtype=np.uint8))
    np.savez_compressed(masks / "mask-1.npz", mask=np.ones((8, 8, 3), dtype=np.uint8))
    np.savez_compressed(states / "state-1.npz", state=np.zeros(7, dtype=np.float32))

    obs = _resolve_observation(_payload(), {"artifact_dir": str(tmp_path)})
    assert obs is not None
    assert set(obs) == {OBS_EGO_RGB, OBS_TARGET_MASK, OBS_STATE}
    assert obs[OBS_EGO_RGB].shape == (8, 8, 3)
    assert obs[OBS_TARGET_MASK].shape == (8, 8, 3)
    assert obs[OBS_STATE].shape == (7,)


def test_resolve_observation_returns_none_when_mask_missing(tmp_path):
    frames = tmp_path / "frames"
    states = tmp_path / "states"
    for d in (frames, states):
        d.mkdir()
    np.savez_compressed(frames / "frame-1.npz", image=np.zeros((8, 8, 3), dtype=np.uint8))
    np.savez_compressed(states / "state-1.npz", state=np.zeros(7, dtype=np.float32))

    # No masks/ directory -> maskRef unresolved -> None (do not guess missing data).
    assert _resolve_observation(_payload(), {"artifact_dir": str(tmp_path)}) is None


def test_resolve_observation_returns_none_without_artifact_dir():
    assert _resolve_observation(_payload(), {}) is None


def test_infer_image_keys_filters_only_images():
    class _Cfg:
        def __init__(self) -> None:
            self.observation_features = {
                "observation.images.ego_rgb": {},
                "observation.images.target_mask": {},
                "observation.state": {},
            }

    keys = _infer_image_keys(_Cfg())
    assert set(keys) == {OBS_EGO_RGB, OBS_TARGET_MASK}
