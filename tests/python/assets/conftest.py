"""Synthetic POSIX metadata for fixed-site installer unit tests."""
import os
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def private_cloud_review(monkeypatch):
    """Keep real file checks/I/O; control only registered private fixture paths.

    A hosted runner cannot chown fixtures to the production Ubuntu uid 1000.
    Exercise that guard on every platform without changing process privileges.
    """
    receipts = {}
    original_stat = type(Path()).stat

    def stat(path, *args, **kwargs):
        info = original_stat(path, *args, **kwargs)
        metadata = receipts.get(path)
        if metadata is None:
            return info
        fields = list(info)
        fields[0], fields[4] = metadata['mode'], metadata['uid']
        return os.stat_result(fields)

    monkeypatch.setattr(type(Path()), 'stat', stat)

    def register(module, path, *, mode=0o100600):
        # Replace this module's os reference, never the shared os.name used by
        # pathlib/pytest to choose native path implementations.
        attributes = vars(module.os).copy()
        attributes['name'] = 'posix'
        monkeypatch.setattr(module, 'os', SimpleNamespace(**attributes))
        metadata = {'uid': 1000, 'mode': mode}
        receipts[path] = metadata
        return metadata

    return register
