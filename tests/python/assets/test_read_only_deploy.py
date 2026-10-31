import importlib.util
from pathlib import Path
from unittest.mock import patch


def test_database_outage_cannot_skip_filesystem_and_service_rollback(tmp_path):
    path = Path(__file__).resolve().parents[3] / 'tools/operations/staging_read_only_sdk.py'
    spec = importlib.util.spec_from_file_location('readonly_deploy', path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    config = [tmp_path / name for name in ['cloud.env', 'stage.conf', 'edge.conf', 'routing.conf']]
    for item in config:
        item.write_text('original')
    root = tmp_path / 'review'; root.mkdir()
    commands, switches = [], []
    def install(*_):
        for item in config:
            item.write_text('candidate')
        return tmp_path / 'candidate'
    def run(arguments, *_, **__):
        commands.append(arguments)
        if arguments[0] == '/usr/sbin/runuser':
            raise OSError('database unavailable')
        return ''
    with patch.object(module, 'CONFIG', config), patch.object(module, 'review', return_value=({}, {}, {})), \
         patch.object(module, 'install_release', side_effect=install), patch.object(module, 'run', side_effect=run), \
         patch.object(module, 'switch_release', side_effect=switches.append), patch.object(module.subprocess, 'run'):
        try:
            module.apply(root, tmp_path / 'not-read.key')
        except OSError:
            pass
    assert all(item.read_text() == 'original' for item in config)
    assert module.OLD in switches
    assert ['systemctl', 'restart', 'thirdhand-stage.service'] in commands


def test_new_device_route_is_added_only_to_https_when_http_also_has_a_404_location():
    path = Path(__file__).resolve().parents[3] / 'tools/operations/staging_read_only_sdk.py'
    spec = importlib.util.spec_from_file_location('readonly_https', path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    http = 'server {\n    listen 80;\n    server_name edge.uiea-thirdhand.com;\n    location / { return 404; }\n}\n'
    https = 'server {\n    listen 443 ssl;\n    server_name edge.uiea-thirdhand.com;\n    location / { return 404; }\n}\n'
    addition = 'location = /edge/v1/telemetry-batches { proxy_pass http://private; }\n'
    result = module.add_https_location(http + https, addition, 'edge.uiea-thirdhand.com')
    assert result.startswith(http)
    assert result.count(addition) == 1
    assert result.index(addition) > len(http)
