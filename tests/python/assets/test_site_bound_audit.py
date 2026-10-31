"""Exact one-time operations exceptions never exempt portable runtime code."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / 'tools/diagnostics/audit_boundaries.py'


def fixture(tmp_path, monkeypatch, *, name='tools/operations/fixed_review.py', extra=''):
    spec = importlib.util.spec_from_file_location('site_audit_fixture', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, '_tracked_files', lambda root: [])
    source = "TARGET = '/home/test_operator/approved-directory'\n" + extra
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding='utf-8')
    manifest = tmp_path / 'configs/audit/site-bound-operations.json'
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({'format': 1, 'files': [{
        'path': name, 'sha256_lf': hashlib.sha256(source.encode()).hexdigest(),
        'reason': 'Reviewed immutable one-time operation.'}]}), encoding='utf-8')
    return module, path


def test_exact_reviewed_operation_is_allowed(tmp_path, monkeypatch):
    module, _ = fixture(tmp_path, monkeypatch)
    assert module.audit_repository(tmp_path) == []


def test_editing_reviewed_operation_invalidates_its_exception(tmp_path, monkeypatch):
    module, path = fixture(tmp_path, monkeypatch)
    path.write_text(path.read_text() + "OTHER = '/home/test_operator/unreviewed'\n")
    errors = module.audit_repository(tmp_path)
    assert len(errors) == 2
    assert {e.code for e in errors} == {'absolute_home_path'}


def test_runtime_code_cannot_be_exempted(tmp_path, monkeypatch):
    module, _ = fixture(tmp_path, monkeypatch, name='apps/web/runtime.py')
    with pytest.raises(ValueError, match='scope'):
        module.audit_repository(tmp_path)


def test_other_boundaries_remain_enforced_for_site_operations(tmp_path, monkeypatch):
    module, _ = fixture(tmp_path, monkeypatch, extra="command = ['python', 'History/old.py']\n")
    assert [e.code for e in module.audit_repository(tmp_path)] == ['history_runtime_dependency']


def test_an_unknown_operation_is_not_exempted(tmp_path, monkeypatch):
    module, _ = fixture(tmp_path, monkeypatch)
    path = tmp_path / 'tools/operations/unknown.py'
    path.write_text("TARGET = '/home/test_operator/unreviewed'\n")
    assert [(e.code, e.path) for e in module.audit_repository(tmp_path)] == [
        ('absolute_home_path', 'tools/operations/unknown.py')]
