#!/usr/bin/env python3
"""Convert checked ThirdHand vision JSONL into runtime Observation JSONL."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from uiea_thirdhand_vla.orchestration.runtime.ports import ObservationUnavailable
from uiea_thirdhand_vla.orchestration.runtime.trace import canonical_json
from uiea_thirdhand_vla.orchestration.shadow.vision_events import VisionEventAdapter
from uiea_thirdhand_vla.orchestration.shadow.vision_sources import (
    VisionEventSourceError,
    VisionJsonlReplaySource,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--episode-id", required=True)
    return parser.parse_args()


def checked_new_output(path: Path) -> Path:
    if path.is_symlink():
        raise ValueError(f"output cannot be a symlink: {path}")
    if path.exists():
        raise ValueError(f"output already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def main() -> int:
    args = parse_args()
    try:
        source = VisionJsonlReplaySource(
            args.events,
            VisionEventAdapter(args.episode_id),
        )
        observations = []
        after_sequence = None
        while True:
            try:
                observation = source.next_observation(after_sequence)
            except ObservationUnavailable:
                break
            observations.append(observation)
            after_sequence = observation.sequence
        output = checked_new_output(args.output)
        output.write_text(
            "".join(canonical_json(item) + "\n" for item in observations),
            encoding="utf-8",
        )
    except (OSError, ValueError, VisionEventSourceError) as exc:
        print(f"vision event replay rejected: {exc}", file=sys.stderr)
        return 2
    summary = {
        "actionable_count": sum(
            item.actionable for observation in observations for item in observation.objects
        ),
        "first_sequence": observations[0].sequence,
        "last_sequence": observations[-1].sequence,
        "observation_count": len(observations),
        "robot_execution_enabled": False,
    }
    print(canonical_json(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
