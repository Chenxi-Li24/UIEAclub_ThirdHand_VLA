from pathlib import Path

from tools.diagnostics.audit_boundaries import audit_repository


ROOT = Path(__file__).resolve().parents[3]


def test_unified_foundation_has_no_machine_specific_runtime_paths():
    violations = audit_repository(ROOT)
    relevant = [item for item in violations if item.code == "absolute_home_path"]
    assert relevant == []


def test_formal_source_does_not_import_history():
    violations = audit_repository(ROOT)
    relevant = [item for item in violations if item.code == "history_runtime_dependency"]
    assert relevant == []


def test_audit_detects_history_runtime_dependency(tmp_path, monkeypatch):
    formal_file = tmp_path / "apps" / "web" / "server.js"
    formal_file.parent.mkdir(parents=True)
    formal_file.write_text('require("../../History/legacy-web/old")\n', encoding="utf-8")
    monkeypatch.setattr(
        "tools.diagnostics.audit_boundaries._tracked_files", lambda _root: []
    )

    violations = audit_repository(tmp_path)

    assert [item.code for item in violations] == ["history_runtime_dependency"]


def test_unlisted_local_payloads_runtime_state_and_external_symlinks_are_absent():
    violations = audit_repository(ROOT)
    relevant = [
        item
        for item in violations
        if item.code in {"tracked_local_payload", "tracked_runtime_payload", "external_symlink"}
    ]
    assert relevant == []


def test_only_manifest_listed_assets_are_allowed(tmp_path, monkeypatch):
    import json
    manifest = tmp_path / 'configs/assets/runtime-assets.json'
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({'files': [
        {'path': 'local/models/allowed.bin'},
        {'path': 'local/runtimes/python/bin/python'},
        {'path': 'local/sdk/.env'},
    ]}))
    monkeypatch.setattr('tools.diagnostics.audit_boundaries._tracked_files', lambda _root: [
        'local/models/allowed.bin', 'local/models/unlisted.bin',
        'local/runtimes/python/bin/python', 'local/sdk/.env', 'runtime/token',
    ])
    violations = audit_repository(tmp_path)
    assert {v.path for v in violations} == {
        'local/models/unlisted.bin', 'local/runtimes/python/bin/python',
        'local/sdk/.env', 'runtime/token',
    }
