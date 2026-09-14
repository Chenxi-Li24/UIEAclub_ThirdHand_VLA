"""Show where teammate-owned context enrichment and target selection attach."""

from __future__ import annotations

import json

from _bootstrap import add_checkout_src

add_checkout_src()

from thirdhand_vision.extensions import TargetSelection

from _mock_pipeline import build_pipeline, fixture_frame


class QueryMatchEnricher:
    name = "query-match"

    def enrich(self, frame, result, context):
        query = str(context.get("query", "")).strip().lower()
        return {
            item.detection.detection_id: {
                "query_match": item.detection.label.lower() == query,
            }
            for item in result.instances
        }


class ExistingTargetSelector:
    name = "existing-target"

    def select(self, result, context):
        query = str(context.get("query", "")).strip().lower()
        for item in result.instances:
            if item.identity_id is not None and item.detection.label.lower() == query:
                return TargetSelection(item.identity_id, 1.0, "exact label match")
        return None


def main() -> None:
    pipeline = build_pipeline(
        enrichers=(QueryMatchEnricher(),),
        selector=ExistingTargetSelector(),
    )
    result = pipeline.process(fixture_frame(), {"query": "bottle"})
    print(json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
