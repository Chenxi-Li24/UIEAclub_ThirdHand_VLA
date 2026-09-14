import json
from pathlib import Path

import pytest

from uiea_thirdhand_vla.orchestration.runtime.ports import ObservationUnavailable
from uiea_thirdhand_vla.orchestration.shadow.vision_events import VisionEventAdapter
from uiea_thirdhand_vla.orchestration.shadow.vision_sources import (
    LatestVisionEventSource,
    VisionEventSourceError,
    VisionJsonlReplaySource,
)

from .sample_events import bottle_event_payload


def write_jsonl(path: Path, payloads: tuple[dict[str, object], ...]) -> None:
    path.write_text(
        "".join(json.dumps(payload, allow_nan=False) + "\n" for payload in payloads),
        encoding="utf-8",
    )


def test_jsonl_replay_emits_strictly_ordered_observations(tmp_path: Path):
    path = tmp_path / "events.jsonl"
    write_jsonl(path, (bottle_event_payload(1), bottle_event_payload(2)))
    source = VisionJsonlReplaySource(path, VisionEventAdapter("episode-vision-1"))

    assert source.next_observation(None).sequence == 1
    assert source.next_observation(1).sequence == 2
    with pytest.raises(ObservationUnavailable, match="exhausted"):
        source.next_observation(2)


def test_jsonl_replay_rejects_rollback_and_malformed_lines(tmp_path: Path):
    rollback = tmp_path / "rollback.jsonl"
    write_jsonl(rollback, (bottle_event_payload(2), bottle_event_payload(1)))
    malformed = tmp_path / "malformed.jsonl"
    malformed.write_text("{not-json}\n", encoding="utf-8")

    with pytest.raises(VisionEventSourceError, match="strictly increasing"):
        VisionJsonlReplaySource(rollback, VisionEventAdapter("episode-vision-1"))
    with pytest.raises(VisionEventSourceError, match="line 1"):
        VisionJsonlReplaySource(malformed, VisionEventAdapter("episode-vision-1"))


def test_sources_reject_symlinks_and_directories(tmp_path: Path):
    target = tmp_path / "event.json"
    target.write_text(json.dumps(bottle_event_payload()), encoding="utf-8")
    link = tmp_path / "event-link.json"
    link.symlink_to(target)
    adapter = VisionEventAdapter("episode-vision-1")

    with pytest.raises(VisionEventSourceError, match="symlink"):
        VisionJsonlReplaySource(link, adapter)
    with pytest.raises(VisionEventSourceError, match="regular file"):
        LatestVisionEventSource(tmp_path, adapter, timeout_s=0.0)


def test_latest_file_source_reads_new_stable_event(tmp_path: Path):
    path = tmp_path / "latest.json"
    path.write_text(json.dumps(bottle_event_payload(3)), encoding="utf-8")
    source = LatestVisionEventSource(
        path,
        VisionEventAdapter("episode-vision-1"),
        timeout_s=0.0,
    )

    observation = source.next_observation(2)

    assert observation.sequence == 3
    assert observation.objects[0].identity_id == 2


def test_latest_file_source_times_out_when_sequence_is_not_new(tmp_path: Path):
    path = tmp_path / "latest.json"
    path.write_text(json.dumps(bottle_event_payload(3)), encoding="utf-8")
    source = LatestVisionEventSource(
        path,
        VisionEventAdapter("episode-vision-1"),
        timeout_s=0.0,
    )

    with pytest.raises(ObservationUnavailable, match="newer than 3"):
        source.next_observation(3)


def test_latest_file_source_rejects_malformed_event(tmp_path: Path):
    path = tmp_path / "latest.json"
    path.write_text("[]", encoding="utf-8")
    source = LatestVisionEventSource(
        path,
        VisionEventAdapter("episode-vision-1"),
        timeout_s=0.0,
    )

    with pytest.raises(VisionEventSourceError, match="cannot parse"):
        source.next_observation(None)
