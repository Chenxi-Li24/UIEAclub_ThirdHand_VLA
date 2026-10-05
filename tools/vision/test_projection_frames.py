import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from handeye_projection_with_frames import HandEyeProjection

ROOT=Path(__file__).resolve().parents[2]
class ProjectionFrameTests(unittest.TestCase):
    def projection(self,marker=True):
        root=Path(tempfile.mkdtemp(prefix='flange-projection-test-'))
        data={'schema':'thirdhand-handeye-calibration-v3','robot_state_semantics':'T_base_flange',
              'extrinsic_semantics':'T_flange_camera','T_flange_camera':{'matrix_4x4':np.eye(4).tolist()},
              'camera':{'camera_serial':'test','registration_id':'test','camera_mount_id':'test'},
              'numerically_validated':True,'physical_validation':{'status':'pending'}}
        if marker:data['frame_normalization']={'policy_id':'sha256:'+'a'*64}
        p=root/'cal.json';p.write_text(json.dumps(data))
        return HandEyeProjection(p,'test','test','test',ROOT/'assets/robot/startouch-v3/FastTouchV3.SLDASM.urdf',allow_numerical_only=True)
    def message(self,projection):
        # Canonical input generated from the URDF; wrong-pose cases modify it.
        fk=projection.chain.forward_kinematics([0]*7)
        from handeye_projection_with_frames import flange_transform
        # zero-joint orientation is identity for this robot.
        np.testing.assert_allclose(fk[:3,:3],np.eye(3),atol=1e-9)
        return {'type':'arm_state','pose_frame':'robot_flange','connected':True,'healthy':True,'stationary':True,
                'flange_position_m':fk[:3,3].tolist(),'flange_euler_rad':[0,0,0],
                'joints_deg':[0]*6,'observed_monotonic_ns':1_000_000_000,
                'frame_normalization':{'policy_id':'sha256:'+'a'*64}}
    def test_rejects_unconverted_calibration(self):
        with self.assertRaisesRegex(ValueError,'frame_policy_required'):self.projection(False)
    def test_rejects_sdk_tool_pose_even_in_numerical_mode(self):
        p=self.projection();m=self.message(p);m['flange_position_m'][0]+=.17334
        self.assertFalse(p.update(m,1_000_000_000))
        self.assertIsNone(p.for_frame(1_000_000_000))
    def test_rejects_mismatched_frame_policy(self):
        p=self.projection();m=self.message(p);m['frame_normalization']['policy_id']='sha256:'+'b'*64
        self.assertFalse(p.update(m,1_000_000_000))
    def test_canonical_numerical_feedback_is_read_only_and_not_approved(self):
        p=self.projection();self.assertTrue(p.update(self.message(p),1_000_000_000))
        self.assertIsNotNone(p.for_frame(1_000_000_000))
        self.assertFalse(p.physically_validated)

    def test_malformed_marker_invalidates_a_previously_valid_pose(self):
        p=self.projection();self.assertTrue(p.update(self.message(p),1_000_000_000))
        m=self.message(p);m['frame_normalization']='bad-marker'
        self.assertFalse(p.update(m,1_000_000_000))
        self.assertIsNone(p.for_frame(1_000_000_000))

if __name__=='__main__':unittest.main()
