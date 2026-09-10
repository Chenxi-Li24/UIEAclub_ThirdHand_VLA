from pathlib import Path

from tools.diagnostics.audit_boundaries import audit_repository


ROOT = Path(__file__).resolve().parents[3]


def test_unified_foundation_has_no_machine_specific_runtime_paths():
    violations = audit_repository(ROOT)
    relevant = [item for item in violations if item.code == "absolute_home_path"]
    assert relevant == []


def test_formal_source_does_not_import_archive():
    violations = audit_repository(ROOT)
    relevant = [item for item in violations if item.code == "archive_runtime_dependency"]
    assert relevant == []


def test_local_runtime_payloads_and_external_symlinks_are_absent():
    violations = audit_repository(ROOT)
    relevant = [
        item
        for item in violations
        if item.code in {"tracked_local_payload", "tracked_runtime_payload", "external_symlink"}
    ]
    assert relevant == []
