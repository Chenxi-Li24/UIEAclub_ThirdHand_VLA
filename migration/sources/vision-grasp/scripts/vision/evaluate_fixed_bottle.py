#!/usr/bin/env python3
import argparse, json
from pathlib import Path
from thirdhand_va.vision.evaluation import aggregate_metrics

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if not isinstance(manifest.get("samples"), list):
        raise SystemExit("manifest must contain a samples list")
    report = aggregate_metrics(manifest["samples"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(args.output)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["passed"] else 2

if __name__ == "__main__":
    raise SystemExit(main())
