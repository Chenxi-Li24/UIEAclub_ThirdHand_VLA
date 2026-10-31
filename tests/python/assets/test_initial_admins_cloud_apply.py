import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

stubs = {'fcntl': types.SimpleNamespace(flock=Mock(), LOCK_EX=2, LOCK_NB=4),
         'pwd': types.SimpleNamespace(getpwnam=Mock())} if sys.platform == 'win32' else {}
with patch.dict(sys.modules, stubs):
    spec = importlib.util.spec_from_file_location('apply_initial_admins', Path(__file__).resolve().parents[3] / 'tools/operations/activate_initial_admins.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)


class DeploymentStateTests(unittest.TestCase):
    def test_absent_batch_is_not_imported(self):
        with patch.object(module, 'sql', return_value=''):
            self.assertIs(module.durable_import_state(), False)

    def test_empty_batch_is_not_imported(self):
        with patch.object(module, 'sql', side_effect=['auth.initial_admin_batch', '0']) as query:
            self.assertIs(module.durable_import_state(), False)
            self.assertIn('pg_advisory_xact_lock(240103,2)',query.call_args.args[0])
            self.assertIn('READ COMMITTED',query.call_args.args[0])

    def test_committed_batch_prevents_old_handler_rollback(self):
        with patch.object(module, 'sql', side_effect=['auth.initial_admin_batch', '1']):
            self.assertIs(module.durable_import_state(), True)

    def test_unavailable_database_is_uncertain_not_uncommitted(self):
        with patch.object(module, 'sql', side_effect=OSError('synthetic outage')):
            self.assertIsNone(module.durable_import_state())

    def test_admission_guard_rejects_occupied_control_without_running_action(self):
        process=Mock()
        process.stdout.readline.return_value='LEASE_GUARD_READY:1\n'
        process.poll.return_value=None
        ready=Mock();ready.select.return_value=[True]
        with patch.object(module.subprocess, 'Popen', return_value=process), patch.object(module.selectors, 'DefaultSelector') as selector:
            selector.return_value.__enter__.return_value=ready
            with self.assertRaises(AssertionError):
                with module.quiescent_lease_admission():
                    self.fail('must not stop service with an active lease')
        self.assertIn('LOCK TABLE ops.control_leases IN SHARE MODE',process.stdin.write.call_args.args[0])
        process.communicate.assert_called_once()

    def test_admission_guard_holds_transaction_until_action_finishes(self):
        process=Mock();process.stdout.readline.return_value='LEASE_GUARD_READY:0\n';process.poll.return_value=None
        ready=Mock();ready.select.return_value=[True]
        with patch.object(module.subprocess, 'Popen', return_value=process), patch.object(module.selectors, 'DefaultSelector') as selector:
            selector.return_value.__enter__.return_value=ready
            with module.quiescent_lease_admission():
                process.communicate.assert_not_called()
        process.communicate.assert_called_once()


if __name__ == '__main__':
    unittest.main()
