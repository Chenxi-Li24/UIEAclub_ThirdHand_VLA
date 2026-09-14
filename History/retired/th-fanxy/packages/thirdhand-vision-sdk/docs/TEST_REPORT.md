# Verification Report

Date: 2026-08-06 (Asia/Shanghai)

## Environment

- Python: 3.11.15
- NumPy: 2.2.6
- SciPy: 1.15.3
- PyYAML: 6.0.2
- OpenCV: 5.0.0
- SDK version: 0.1.0

## Repository verification

Command:

```bash
python -m pytest -q
```

Result: exit code 0, `65 passed`.

Commands:

```bash
python examples/minimal_mock.py
python examples/multimodal_extension.py
```

Result: both exited with code 0 and emitted valid JSON. The minimal result contained
one `bottle` instance; the extension example selected that existing visual identity.

Command:

```bash
python scripts/verify_source_unchanged.py --source-root "$(git rev-parse --show-toplevel)"
```

Result: exit code 0; every selected original source file matched its recorded SHA-256.

## Release guard and archive inspection

Command:

```bash
python -m pytest tests/test_release_contents.py -q
```

Result: exit code 0, `18 passed`. The guard covers the explicit allowlist,
deterministic timestamps, manifest inclusion, forbidden weights/captures/logs/keys,
symlinks, hardware or CAN runtime imports, credential markers, and absolute paths in
configuration files.

The pre-report validation archive contained 56 sorted entries, no forbidden entry,
and had SHA-256
`d83cd313e8d147ac6d9853a02c5d9c02a80a5c48f7fd4db6e4a5d394c12c1bab`.
The final archive is rebuilt with this report included; its authoritative SHA-256 is
stored in the adjacent `thirdhand-vision-sdk-20260806.zip.sha256` sidecar. The final
hash cannot be embedded inside the archive it hashes without creating a circular
artifact.

## Extracted-archive installation

The archive was extracted to a fresh temporary directory. A new virtual environment
was created with host base dependencies available, and package installation was run
with networking disabled:

```bash
PIP_NO_INDEX=1 python -m pip install --no-deps --no-build-isolation ./thirdhand-vision-sdk
python -c "from thirdhand_vision import VisionPipeline; print(VisionPipeline.__name__)"
python -m pytest -q
python examples/minimal_mock.py
```

Results: all commands exited with code 0; the import printed `VisionPipeline`, the
extracted suite reported `65 passed`, and the example returned one instance.

## Scope boundary

These checks are intentionally hardware-free and offline. They do not claim tests
against a Lumos camera, RealSense D435, robot, CAN bus, GPU, RTMDet checkpoint,
DINOv2 weights, network service, or production calibration. Optional model adapters
were contract-tested using fakes and lazy-import checks; actual model accuracy and
hardware integration remain deployment responsibilities.
