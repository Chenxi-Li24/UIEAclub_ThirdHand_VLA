# Historical Calibration Source

This archive preserves the ignored `local/calibration/source` material
from the primary deployment directory. It includes earlier Lumos and D435
experiments, old calibration results, and legacy bottle-grasp programs.
It is not the current XVisio handeye evidence and is never loaded by a
default service. None of the numerical values is changed or approved by
this migration. Some old scripts can construct an SDK and send motion;
do not run them as verification commands.

`source-manifest.json` records all 30 non-cache files and their original
SHA-256 and size. Python/text/JSON sources are retained for traceability.
The two old model weights and captured NPZ are kept locally under `source`
but excluded from Git: these were marked local-only and their distribution
and captured-image privacy have not been separately approved. They are not
required by the current runtime. Byte-level presence is checked separately
from Git coverage; do not interpret a manifest as an approved calibration.

The original files remain untouched at the primary deployment directory.
All current service configuration uses the formal calibration locations,
not this historical archive.
