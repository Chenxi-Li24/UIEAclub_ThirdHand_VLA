import importlib.util
from pathlib import Path


def load_script():
    path = Path("scripts/vision/debug_pipeline.py")
    spec = importlib.util.spec_from_file_location("debug_pipeline", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_debug_pipeline_accepts_stable_target_id_not_spatial_ordinal() -> None:
    module = load_script()

    args = module.build_parser().parse_args(
        ["--target-id", "2", "--request-id", "debug-2", "bundle-a", "bundle-b"]
    )

    assert args.target_id == 2
    assert args.request_id == "debug-2"
    assert not hasattr(args, "side")
    assert not hasattr(args, "ordinal")
