"""Exercise the migration CLI; source data is immutable, approval stays false."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import numpy as np

HERE=Path(__file__).resolve().parent
class MigrationTests(unittest.TestCase):
    def run_migration(self, source, tool):
        root=Path(tempfile.mkdtemp(prefix='frame-migration-test-'))
        raw=json.dumps(source).encode(); (root/'source.json').write_bytes(raw)
        policy={'schema':'thirdhand-robot-frame-policy-v1','source_semantics':'sdk_tool_mislabeled_as_robot_flange',
                'T_flange_sdk_tool':tool,'legacy_calibration_sha256':hashlib.sha256(raw).hexdigest()}
        (root/'policy.json').write_text(json.dumps(policy))
        result=subprocess.run([sys.executable,str(HERE/'migrate_handeye_frames.py'),'--source',str(root/'source.json'),
                               '--policy',str(root/'policy.json'),'--output',str(root/'derived')],capture_output=True,text=True)
        return root,raw,result
    def source(self):
        return {'schema':'thirdhand-handeye-calibration-v3','extrinsic_semantics':'T_flange_camera',
                'robot_state_semantics':'T_base_flange','T_flange_camera':{'matrix_4x4':[[1,0,0,-.08],[0,1,0,.01],[0,0,1,.07],[0,0,0,1]]},
                'numerically_validated':True,'approved_for_bottle_grasp':False,
                'physical_validation':{'status':'pending'}}
    def test_converts_extrinsic_and_preserves_source_and_approval(self):
        root,raw,result=self.run_migration(self.source(),[[1,0,0,.17334],[0,1,0,0],[0,0,1,0],[0,0,0,1]])
        self.assertEqual(result.returncode,0,result.stderr)
        converted=json.loads((root/'derived'/'handeye-flange.json').read_text())
        self.assertEqual((root/'source.json').read_bytes(),raw)
        self.assertAlmostEqual(converted['T_flange_camera']['matrix_4x4'][0][3],.09334)
        self.assertFalse(converted['approved_for_bottle_grasp'])
        self.assertEqual(converted['physical_validation']['status'],'pending')
        self.assertTrue(converted['frame_normalization']['policy_id'].startswith('sha256:'))
    def test_base_camera_pose_is_invariant_under_rotated_flange(self):
        root,raw,result=self.run_migration(self.source(),[[1,0,0,.17334],[0,1,0,0],[0,0,1,0],[0,0,0,1]])
        self.assertEqual(result.returncode,0,result.stderr)
        new=np.array(json.loads((root/'derived'/'handeye-flange.json').read_text())['T_flange_camera']['matrix_4x4'])
        # SDK tool pose yaw90: flange x=.3, y=0; tool x=.3, y=.17334.
        sdk=np.array([[0,-1,0,.3],[1,0,0,.17334],[0,0,1,.2],[0,0,0,1]])
        flange=np.array([[0,-1,0,.3],[1,0,0,0],[0,0,1,.2],[0,0,0,1]])
        np.testing.assert_allclose(flange@new,sdk@np.asarray(self.source()['T_flange_camera']['matrix_4x4']),atol=1e-12)
    def test_rejects_already_normalized_calibration(self):
        source=self.source();source['frame_normalization']={'policy_id':'already'}
        root,raw,result=self.run_migration(source,np.eye(4).tolist())
        self.assertNotEqual(result.returncode,0)
        self.assertIn('already_normalized',result.stderr)
        self.assertFalse((root/'derived'/'handeye-flange.json').exists())
    def test_rejects_non_rigid_tool_transform(self):
        tool=np.eye(4);tool[0,0]=2
        root,raw,result=self.run_migration(self.source(),tool.tolist())
        self.assertNotEqual(result.returncode,0)
        self.assertIn('non_rigid',result.stderr)
        self.assertFalse((root/'derived'/'handeye-flange.json').exists())

if __name__=='__main__':unittest.main()
