import math
import unittest
import numpy as np
import cv2
from handeye_core import flange_transform, validate_state, solve_handeye, match_state, fit_camera


class CoreTests(unittest.TestCase):
    def test_euler_is_not_rodrigues(self):
        t = flange_transform([1, 2, 3], [math.pi/2, 0, math.pi/2])
        np.testing.assert_allclose(t[:3,:3], [[0,0,1],[1,0,0],[0,1,0]], atol=1e-9)
        np.testing.assert_allclose(t[:3,3], [1,2,3])

    def state(self):
        return dict(type='robot_state', connected=True, healthy=True, moving=False,
                    pose_frame='robot_flange', state_sequence=4, producer_monotonic_ns=1000000000,
                    flange_position_m=[0,0,0], flange_euler_rad=[0,0,0],
                    velocities_deg_s=[0]*6, joints_deg=[0]*6)

    def test_bad_or_moving_state_is_rejected(self):
        self.assertIsNotNone(validate_state(self.state(), 1100000000))
        for field, value in [('moving',True), ('healthy',False), ('pose_frame','robot_tcp'),
                             ('flange_position_m',[float('nan'),0,0]), ('state_sequence',True),
                             ('producer_monotonic_ns',1200000000), ('velocities_deg_s',[3]*6)]:
            with self.subTest(field=field):
                s=self.state(); s[field]=value
                self.assertIsNone(validate_state(s,1100000000))
        self.assertIsNone(validate_state(self.state(),2000000000))

    def test_pair_requires_nearby_stationary_state(self):
        s=self.state()
        after={**s,'state_sequence':5,'producer_monotonic_ns':1100000000}
        self.assertEqual(match_state([s,after],1050000000,1100000000)['state_sequence'],4)
        with self.assertRaises(ValueError): match_state([s],1400000000,1450000000)
        s['moving']=True
        with self.assertRaises(ValueError): match_state([s],1050000000,1100000000)

    def test_motion_between_stopped_poses_cannot_be_a_sample(self):
        s=self.state();after={**s,'state_sequence':5,'producer_monotonic_ns':1200000000,
                            'flange_position_m':[.02,0,0]}
        with self.assertRaises(ValueError):match_state([s,after],1100000000,1250000000)
        mid={**s,'state_sequence':5,'producer_monotonic_ns':1050000000,'moving':True}
        after={**s,'state_sequence':6,'producer_monotonic_ns':1100000000}
        with self.assertRaises(ValueError):match_state([s,mid,after],1070000000,1150000000)

    def test_invalid_or_backwards_intervening_feedback_is_not_filtered_out(self):
        s=self.state();after={**s,'state_sequence':6,'producer_monotonic_ns':1100000000}
        for mid in [{'type':'robot_state','moving':True},
                    {**s,'state_sequence':5,'producer_monotonic_ns':990000000,'moving':True}]:
            with self.assertRaises(ValueError):match_state([s,mid,after],1050000000,1150000000)

    def test_known_handeye_and_heldout_pose(self):
        x=flange_transform([.03,-.04,.08],[.2,-.1,.3])
        board=flange_transform([.4,.1,.25],[.1,.2,-.1])
        pairs=[]
        for i in range(18):
            a=flange_transform([.2+.01*i,.03*math.cos(i),.2+.02*math.sin(i)],
                               [.6*math.sin(i),.5*math.cos(i*.7),.4*math.sin(i*.4)])
            b=np.linalg.inv(x)@np.linalg.inv(a)@board
            pairs.append((a,b))
        report=solve_handeye(pairs)
        np.testing.assert_allclose(report['T_flange_camera'],x,atol=1e-5)
        self.assertLess(report['held_out_max_translation_m'],1e-5)
        self.assertFalse(report['approved_for_bottle_grasp'])
        self.assertEqual(report['physical_validation'],'pending')

    def test_no_diversity_or_few_pairs_cannot_solve(self):
        with self.assertRaises(ValueError): solve_handeye([(np.eye(4),np.eye(4))]*6)
        with self.assertRaises(ValueError): solve_handeye([(np.eye(4),np.eye(4))]*18)

    def test_camera_fit_uses_image_coordinates_not_old_intrinsics(self):
        obj=np.array([[x*.015,y*.015,0] for y in range(1,12) for x in range(1,9)],float)
        k=np.array([[220.,0,320.],[0,221.,240.],[0,0,1.]])
        d=np.array([-.02,.005,0.,0.])
        samples=[]
        for i in range(18):
            r=np.array([.25*math.sin(i),.3*math.cos(i*.7),.15*math.sin(i*.4)])
            t=np.array([-.08+.03*math.sin(i*.9),-.09+.02*math.cos(i),.35+.03*math.sin(i*.6)])
            uv,_=cv2.fisheye.projectPoints(obj.reshape(-1,1,3),r,t,k,d)
            samples.append({'object_points':obj.tolist(),'image_points':uv.reshape(-1,2).tolist()})
        out=fit_camera(samples,(640,480))
        np.testing.assert_allclose(out['K'],k,atol=.01)
        self.assertLess(max(out['frame_rmse_px']),.01)
        self.assertEqual(len(out['board_transforms']),18)

if __name__ == '__main__': unittest.main()
