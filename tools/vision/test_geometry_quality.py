import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
import numpy as np
from geometry_quality.pointcloud import fit_table_plane

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('quality_bridge',HERE/'camera_bridge_with_quality.py')
bridge=importlib.util.module_from_spec(spec);spec.loader.exec_module(bridge)

class QualityTests(unittest.TestCase):
    def test_refinement_checks_each_candidate_before_selection(self):
        rng=np.random.default_rng(1)
        a=rng.uniform(-.2,.2,(200,2))
        good=np.column_stack([a,np.full(200,.5)])
        b=rng.uniform(-.015,.015,(1000,2))
        bad=np.column_stack([b[:,0]+.35,b[:,1]+.35,.5+np.tan(np.deg2rad(35))*b[:,1]])
        bad+=rng.normal(0,.0005,(1000,3))
        xyz=np.concatenate([good,bad]).astype(np.float32).reshape(1,-1,3)
        try:
            plane=fit_table_plane(xyz,np.zeros(xyz.shape[:2],bool),distance_m=.008,
                                  normal_hint=np.array([0.,0.,1.]),max_normal_angle_deg=15)
        except ValueError as e:self.fail(f'valid alternative table candidate discarded: {e}')
        self.assertGreaterEqual(plane.normal[2],np.cos(np.deg2rad(15)))
        self.assertGreaterEqual(plane.inlier_count,30)

    def test_wrong_orientation_still_fails_closed(self):
        yy,xx=np.indices((20,20))
        xyz=np.stack([xx*.01,np.full_like(xx,.1,dtype=float),.3+yy*.01],axis=2).astype(np.float32)
        with self.assertRaisesRegex(ValueError,'table_plane'):
            fit_table_plane(xyz,np.zeros((20,20),bool),distance_m=.008,
                            normal_hint=np.array([0.,0.,1.]),max_normal_angle_deg=15)

    def test_display_excludes_background_depth_but_keeps_raw_count(self):
        mask=np.ones((20,25),bool)
        xyz=np.zeros((20,25,3),np.float32)
        xyz[...,2]=.2;xyz.reshape(-1,3)[300:,2]=.8
        frame=SimpleNamespace(depth_m=xyz[...,2],xyz_camera_m=xyz,monotonic_ns=100)
        config=SimpleNamespace(min_depth_m=.15,max_depth_m=1.2,min_depth_points=250,min_depth_ratio=.055)
        track=SimpleNamespace(candidate=SimpleNamespace(detection_id=1,mask=mask),state='confirmed')
        event={'targets':[{'stable_id':1,'detection_id':1,'depth_valid':True,'blockers':[]}]}
        bridge.attach_depth_evidence(event,SimpleNamespace(tracks=[track]),frame,config)
        target=event['targets'][0]
        self.assertLess(target['position_std_m'][2],.005)
        self.assertAlmostEqual(target['depth_m'],.2,places=6)
        self.assertEqual(target['valid_depth_points'],300)
        self.assertEqual(target['raw_valid_depth_points'],500)

    def test_filtered_point_shortage_clears_coordinates(self):
        mask=np.ones((20,25),bool)
        xyz=np.zeros((20,25,3),np.float32)
        xyz[...,2]=np.nan
        xyz.reshape(-1,3)[:200,2]=.2
        xyz.reshape(-1,3)[200:350,2]=.8
        frame=SimpleNamespace(depth_m=xyz[...,2],xyz_camera_m=xyz,monotonic_ns=100)
        config=SimpleNamespace(min_depth_m=.15,max_depth_m=1.2,min_depth_points=250,min_depth_ratio=.055)
        track=SimpleNamespace(candidate=SimpleNamespace(detection_id=1,mask=mask),state='confirmed')
        target={'stable_id':1,'detection_id':1,'depth_valid':True,'blockers':[],
                'camera_xyz_m':[1,2,3],'base_xyz_m':[1,2,3],'depth_m':1.}
        bridge.attach_depth_evidence({'targets':[target]},SimpleNamespace(tracks=[track]),frame,config)
        self.assertFalse(target['depth_valid'])
        self.assertIsNone(target['camera_xyz_m'])
        self.assertIsNone(target['base_xyz_m'])
        self.assertIsNone(target['depth_m'])
        self.assertEqual(target['valid_depth_points'],200)
        self.assertIn('insufficient_filtered_depth',target['blockers'])

    def test_lost_target_does_not_publish_coordinates(self):
        mask=np.ones((20,25),bool)
        xyz=np.zeros((20,25,3),np.float32);xyz[...,2]=.2
        frame=SimpleNamespace(depth_m=xyz[...,2],xyz_camera_m=xyz,monotonic_ns=100)
        config=SimpleNamespace(min_depth_m=.15,max_depth_m=1.2,min_depth_points=250,min_depth_ratio=.055)
        track=SimpleNamespace(candidate=SimpleNamespace(detection_id=1,mask=mask),state='lost')
        target={'stable_id':1,'detection_id':1,'depth_valid':True,'blockers':[]}
        bridge.attach_depth_evidence({'targets':[target]},SimpleNamespace(tracks=[track]),frame,config)
        self.assertFalse(target['depth_valid'])
        self.assertIsNone(target['camera_xyz_m'])
        self.assertIsNone(target['depth_m'])
        self.assertEqual(target['raw_valid_depth_points'],500)
        self.assertEqual(target['raw_depth_valid_ratio'],1.)

    def test_filtered_ratio_shortage_with_enough_points_fails_closed(self):
        mask=np.ones((100,100),bool)
        xyz=np.zeros((100,100,3),np.float32);xyz[...,2]=np.nan
        xyz.reshape(-1,3)[:300,2]=.2
        frame=SimpleNamespace(depth_m=xyz[...,2],xyz_camera_m=xyz,monotonic_ns=100)
        config=SimpleNamespace(min_depth_m=.15,max_depth_m=1.2,min_depth_points=250,min_depth_ratio=.055)
        track=SimpleNamespace(candidate=SimpleNamespace(detection_id=1,mask=mask),state='confirmed')
        target={'stable_id':1,'detection_id':1,'depth_valid':True,'blockers':[]}
        bridge.attach_depth_evidence({'targets':[target]},SimpleNamespace(tracks=[track]),frame,config)
        self.assertEqual(target['valid_depth_points'],300)
        self.assertAlmostEqual(target['depth_valid_ratio'],.03)
        self.assertFalse(target['depth_valid'])
        self.assertIsNone(target['camera_xyz_m'])

if __name__=='__main__':unittest.main()
