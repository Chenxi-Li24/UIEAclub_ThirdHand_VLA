"""Run the complete public pipeline without weights, GPU, network or hardware."""

from __future__ import annotations

import json

from _bootstrap import add_checkout_src

add_checkout_src()

from _mock_pipeline import build_pipeline, fixture_frame


def main() -> None:
    result = build_pipeline().process(fixture_frame())
    print(json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
