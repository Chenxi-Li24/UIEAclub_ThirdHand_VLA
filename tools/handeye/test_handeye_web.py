import unittest
import tempfile
from pathlib import Path
import numpy as np
import cv2
from handeye_web import CalibrationSession


class WebTests(unittest.TestCase):
    def bundle(self):
        dictionary=cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_5X5_100)
        board=cv2.aruco.CharucoBoard((9,12),.015,.01125,dictionary)
        image=np.full((480,640),255,np.uint8)
        image[40:440,170:470]=board.generateImage((300,400))
        return {'rgb':cv2.cvtColor(image,cv2.COLOR_GRAY2RGB),
                'metadata':{'schema':'thirdhand-raw-rgbd-frame-v1','camera_serial':'250801DR48FP25002738',
                            'point_frame':'xvisio_color','length_unit':'m','monotonic_ns':1000000000,'frame_id':7}}

    def state(self):
        return dict(type='robot_state',connected=True,healthy=True,moving=False,pose_frame='robot_flange',
                    state_sequence=1,producer_monotonic_ns=1000000000,flange_position_m=[0,0,.3],
                    flange_euler_rad=[0,0,0],joints_deg=[0]*6,velocities_deg_s=[0]*6)

    def history(self):
        s=self.state()
        return [s,{**s,'state_sequence':2,'producer_monotonic_ns':1040000000}]

    def test_capture_persists_board_and_correlated_pose(self):
        with tempfile.TemporaryDirectory() as d:
            session=CalibrationSession(Path(d))
            session.capture(self.bundle(),self.history(),1050000000)
            self.assertEqual(len(session.samples),1)
            self.assertGreaterEqual(len(session.samples[0]['image_points']),30)
            self.assertEqual(session.samples[0]['robot_state']['state_sequence'],1)
            self.assertTrue((Path(d)/'sample-0001.npz').is_file())
            with self.assertRaises(ValueError):session.capture(self.bundle(),self.history(),1050000000)
            self.assertEqual(len(session.samples),1)

    def test_candidate_manifest_survives_later_capture(self):
        with tempfile.TemporaryDirectory() as d:
            session=CalibrationSession(Path(d))
            session.capture(self.bundle(),self.history(),1050000000)
            manifest=session.freeze_manifest()
            snapshot=(Path(d)/manifest['filename']).read_bytes()
            bundle=self.bundle();bundle['metadata']['frame_id']=8
            history=[{**s,'flange_euler_rad':[.1,0,0]} for s in self.history()]
            session.capture(bundle,history,1050000000)
            self.assertEqual((Path(d)/manifest['filename']).read_bytes(),snapshot)
            import json,hashlib
            m=json.loads(snapshot)
            self.assertEqual(len(m['samples']),1)
            self.assertEqual(m['artifacts'][0]['sha256'],hashlib.sha256((Path(d)/'sample-0001.npz').read_bytes()).hexdigest())

    def test_invalid_identity_or_motion_never_adds_a_sample(self):
        with tempfile.TemporaryDirectory() as d:
            session=CalibrationSession(Path(d))
            bundle=self.bundle();bundle['metadata']['camera_serial']='other-camera'
            with self.assertRaises(ValueError):session.capture(bundle,[self.state()],1050000000)
            s=self.state();s['moving']=True
            with self.assertRaises(ValueError):session.capture(self.bundle(),[s],1050000000)
            self.assertEqual(session.samples,[])
            self.assertEqual(list(Path(d).iterdir()),[])

    def test_ordinary_bottle_view_not_a_calibration_sample(self):
        with tempfile.TemporaryDirectory() as d:
            session=CalibrationSession(Path(d));bundle=self.bundle();bundle['rgb'][:]=0
            with self.assertRaises(ValueError):session.capture(bundle,[self.state()],1050000000)
            self.assertEqual(session.samples,[])

    def test_restart_preserves_samples_and_replay_protection(self):
        with tempfile.TemporaryDirectory() as d:
            session=CalibrationSession(Path(d))
            session.capture(self.bundle(),self.history(),1050000000)
            resumed=CalibrationSession(Path(d))
            self.assertEqual(len(resumed.samples),1)
            with self.assertRaises(ValueError):resumed.capture(self.bundle(),self.history(),1050000000)

if __name__=='__main__':unittest.main()
