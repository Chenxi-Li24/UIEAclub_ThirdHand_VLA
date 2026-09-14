from dataclasses import replace
from pathlib import Path

import numpy as np

from thirdhand_va.common.config import VisionConfig
from thirdhand_va.common.contracts import RgbdFrame
from thirdhand_va.vision.perception.interfaces import RawCandidate
from thirdhand_va.vision.pipeline import VisionPipeline


class SequenceBackend:
    def __init__(self, frames: list[tuple[RawCandidate, ...]]) -> None:
        self.frames = frames
        self.index = 0

    def infer(self, rgb: np.ndarray) -> tuple[RawCandidate, ...]:
        result = self.frames[min(self.index, len(self.frames) - 1)]
        self.index += 1
        return result

    def model_provenance(self) -> dict[str, str]:
        return {"backend": "sequence-fixture"}


def _mask(center_x: int) -> np.ndarray:
    mask = np.zeros((100, 180), dtype=bool)
    mask[5:25, center_x - 5:center_x + 5] = True
    mask[25:95, center_x - 15:center_x + 15] = True
    return mask


def raw(physical_id: int, detection_id: int, center_x: int) -> RawCandidate:
    descriptor = np.zeros(4, dtype=np.float32)
    descriptor[physical_id] = 1.0
    return RawCandidate(
        detection_id=detection_id,
        prompt_label="bottle",
        score=0.9,
        bbox_xyxy=(center_x - 15, 5, center_x + 15, 95),
        mask=_mask(center_x),
        descriptor=descriptor,
    )


def frame(sequence: int, *, no_depth_physical: int | None = None) -> RgbdFrame:
    yy, xx = np.indices((100, 180))
    xyz = np.empty((100, 180, 3), dtype=np.float32)
    xyz[..., 0] = (xx - 90.0) * 0.002
    xyz[..., 1] = 0.07
    xyz[..., 2] = 0.45 + (yy - 50.0) * 0.0001
    for physical_id, center_x in enumerate((30, 90, 150)):
        mask = _mask(center_x)
        # These fixtures model the user's required separated-bottle layout:
        # adjacent body surfaces remain outside the gripper approach envelope.
        xyz[..., 0][mask] = (center_x - 90.0) * 0.002 + (
            xx[mask] - center_x
        ) * 0.0015
        xyz[..., 1][mask] = (yy[mask] - 50.0) * 0.0015
        xyz[..., 2][mask] = 0.42 + physical_id * 0.03
        if physical_id == no_depth_physical:
            xyz[mask] = np.nan
    return RgbdFrame(
        sequence=sequence,
        monotonic_ns=sequence * 100_000_000,
        camera_serial="250801DR48FP25002738",
        rgb=np.zeros((100, 180, 3), dtype=np.uint8),
        depth_m=xyz[..., 2],
        xyz_camera_m=xyz,
    )


def detections(sequence: int, *, reordered: bool = False) -> tuple[RawCandidate, ...]:
    rows = [
        raw(0, sequence * 100 + 1, 30),
        raw(1, sequence * 100 + 2, 90),
        raw(2, sequence * 100 + 3, 150),
    ]
    return tuple(reversed(rows)) if reordered else tuple(rows)


def confirm_tracks(pipeline: VisionPipeline):
    result = None
    for sequence in range(1, 4):
        current = frame(sequence)
        result = pipeline.process(current, now_ns=current.monotonic_ns + 1_000_000)
    assert result is not None
    return result


def physical_to_stable(decision):
    return {
        int(np.argmax(track.candidate.descriptor)): track.stable_id
        for track in decision.tracks
    }


def test_pipeline_selects_stable_id_after_detector_and_left_right_reorder() -> None:
    backend = SequenceBackend([
        detections(index, reordered=index % 2 == 0) for index in range(1, 9)
    ])
    pipeline = VisionPipeline(VisionConfig.from_yaml(Path("configs/vision.yaml")), backend)
    confirmed = confirm_tracks(pipeline)
    stable_ids = physical_to_stable(confirmed)
    chosen = stable_ids[1]
    assert pipeline.select(chosen, "req-middle") is True

    decisions = []
    for sequence in range(4, 8):
        current = frame(sequence)
        decisions.append(
            pipeline.process(current, now_ns=current.monotonic_ns + 1_000_000)
        )

    ready = decisions[-1]
    assert ready.status == "ready"
    assert ready.selected_stable_id == chosen
    assert int(np.argmax(ready.target.descriptor)) == 1
    assert physical_to_stable(ready) == stable_ids
    assert ready.selection_side is None and ready.requested_ordinal is None
    assert ready.evidence_id.startswith("sha256:")


def test_depth_invalid_bottle_keeps_its_stable_id_and_does_not_shift_others() -> None:
    backend = SequenceBackend([detections(index) for index in range(1, 6)])
    pipeline = VisionPipeline(VisionConfig.from_yaml("configs/vision.yaml"), backend)
    confirmed = confirm_tracks(pipeline)
    before = physical_to_stable(confirmed)

    source = frame(4, no_depth_physical=0)
    result = pipeline.process(source, now_ns=source.monotonic_ns + 1_000_000)
    after = physical_to_stable(result)
    blocked = next(
        track for track in result.tracks
        if int(np.argmax(track.candidate.descriptor)) == 0
    )

    assert before == after
    assert blocked.depth_supported is False
    assert "depth_insufficient" in " ".join(blocked.blockers)


def test_motion_epoch_discards_old_stability_hits_and_requires_stationary_frames() -> None:
    backend = SequenceBackend([detections(index) for index in range(1, 12)])
    pipeline = VisionPipeline(VisionConfig.from_yaml("configs/vision.yaml"), backend)
    confirmed = confirm_tracks(pipeline)
    chosen = physical_to_stable(confirmed)[1]
    assert pipeline.select(chosen, "req-epoch") is True
    # Base +X maps to camera +Z in this fixture, so the validated insertion
    # corridor does not cross the two neighboring bottles arranged on camera X.
    t_base_camera = np.eye(4)
    t_base_camera[:3, :3] = np.asarray([
        [0.0, 0.0, 1.0],
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
    ])
    first = frame(4)
    pipeline.process(
        first,
        now_ns=first.monotonic_ns + 1_000_000,
        t_base_camera=t_base_camera,
    )

    pipeline.begin_motion_epoch(2)
    moving_frame = frame(5)
    moving = pipeline.process(
        moving_frame, now_ns=moving_frame.monotonic_ns + 1_000_000,
        t_base_camera=t_base_camera,
    )

    assert moving.status == "uncertain"
    assert moving.reasons == ("camera_motion_active",)
    assert moving.stable_hits == 0
    assert moving.motion_epoch == 2
    pipeline.set_camera_moving(False)
    stationary = []
    for sequence in range(6, 10):
        current = frame(sequence)
        stationary.append(
            pipeline.process(
                current,
                now_ns=current.monotonic_ns + 1_000_000,
                t_base_camera=t_base_camera,
            )
        )
    assert stationary[-1].status == "ready"
    assert stationary[-1].motion_epoch == 2


def test_motion_epoch_refuses_to_associate_without_reserved_world_anchor() -> None:
    backend = SequenceBackend([detections(index) for index in range(1, 7)])
    pipeline = VisionPipeline(VisionConfig.from_yaml("configs/vision.yaml"), backend)
    confirmed = confirm_tracks(pipeline)
    chosen = physical_to_stable(confirmed)[1]
    assert pipeline.select(chosen, "req-no-anchor") is True

    pipeline.begin_motion_epoch(1)
    current = frame(4)
    result = pipeline.process(
        current,
        now_ns=current.monotonic_ns + 1_000_000,
        t_base_camera=np.eye(4),
    )

    assert result.status == "uncertain"
    assert result.reasons == ("robot_base_anchor_unavailable",)


def test_selection_is_request_bound_idempotent_and_releasable() -> None:
    pipeline = VisionPipeline(
        VisionConfig.from_yaml("configs/vision.yaml"),
        SequenceBackend([detections(index) for index in range(1, 5)]),
    )
    confirmed = confirm_tracks(pipeline)
    chosen = physical_to_stable(confirmed)[0]

    assert pipeline.select(chosen, "req-1") is True
    assert pipeline.select(chosen, "req-1") is False
    assert pipeline.select(5, "req-other") is False
    pipeline.release("req-1")
    assert pipeline.selection is None


def test_pipeline_uses_robot_base_anchors_across_wrist_camera_rotation() -> None:
    identical = np.ones(4, dtype=np.float32) / 2.0

    def lookalikes(sequence: int) -> tuple[RawCandidate, ...]:
        return tuple(
            RawCandidate(
                detection_id=sequence * 10 + index,
                prompt_label="bottle",
                score=0.9,
                bbox_xyxy=(center - 15, 5, center + 15, 95),
                mask=_mask(center),
                descriptor=identical.copy(),
            )
            for index, center in enumerate((30, 150), start=1)
        )

    backend = SequenceBackend([lookalikes(index) for index in range(1, 10)])
    pipeline = VisionPipeline(VisionConfig.from_yaml("configs/vision.yaml"), backend)
    identity = np.eye(4)
    confirmed = None
    for sequence in range(1, 4):
        current = frame(sequence)
        confirmed = pipeline.process(
            current,
            now_ns=current.monotonic_ns + 1_000_000,
            t_base_camera=identity,
        )
    assert confirmed is not None
    left_track = min(confirmed.tracks, key=lambda track: track.centroid_xy[0])
    assert left_track.stable_id is not None
    assert pipeline.select(left_track.stable_id, "req-lookalike") is True

    rotation = np.eye(4)
    rotation[0, 0] = -1.0
    rotation[1, 1] = -1.0
    pipeline.begin_motion_epoch(1)
    moving_frame = frame(4)
    pipeline.process(
        moving_frame,
        now_ns=moving_frame.monotonic_ns + 1_000_000,
        t_base_camera=rotation,
    )
    pipeline.set_camera_moving(False)
    result = None
    for sequence in range(5, 9):
        current = frame(sequence)
        result = pipeline.process(
            current,
            now_ns=current.monotonic_ns + 1_000_000,
            t_base_camera=rotation,
        )

    assert result is not None
    selected = next(
        track for track in result.tracks if track.stable_id == left_track.stable_id
    )
    assert selected.centroid_xy[0] > 90
    assert result.selected_stable_id == left_track.stable_id
