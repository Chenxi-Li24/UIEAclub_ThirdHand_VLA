"""Regression: missing frame-bound transform must not accept a tilted table."""
import importlib.util
import os
from pathlib import Path
import unittest
import numpy as np
from thirdhand_va.common.config import VisionConfig
from thirdhand_va.common.contracts import RgbdFrame
from thirdhand_va.vision.perception.interfaces import RawCandidate

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('projection_bridge',HERE/'camera_bridge_with_projection.py')
bridge=importlib.util.module_from_spec(spec);spec.loader.exec_module(bridge)

class Backend:
    def __init__(self):
        self.mask=np.zeros((100,180),bool)
        self.mask[5:25,85:95]=True
        self.mask[25:95,75:105]=True
    def infer(self,rgb):
        return (RawCandidate(detection_id=1,prompt_label='bottle',score=.99,
                             bbox_xyxy=(75,5,105,95),mask=self.mask,
                             descriptor=np.array([1,0,0,0],np.float32)),)

def frame(mask):
    yy,xx=np.indices(mask.shape)
    xyz=np.empty((*mask.shape,3),np.float32)
    xyz[...,0]=(xx-90)*.002
    xyz[...,1]=.07
    xyz[...,2]=.45+(yy-50)*.0001
    xyz[...,0][mask]=(xx[mask]-90)*.0015
    xyz[...,1][mask]=(yy[mask]-50)*.0015
    xyz[...,2][mask]=.45
    return RgbdFrame(sequence=1,monotonic_ns=100_000_000,camera_serial='250801DR48FP25002738',
                     rgb=np.zeros((*mask.shape,3),np.uint8),depth_m=xyz[...,2],xyz_camera_m=xyz)

class Projection:
    projection_allowed=True
    physically_validated=False
    def __init__(self,transform):self.transform=transform
    def for_frame(self,stamp):
        return self.transform if stamp==100_000_000 else None

class RuntimeTests(unittest.TestCase):
    def runtime(self,transform):
        backend=Backend()
        live=Path(os.environ.get('THIRDHAND_LIVE_ROOT',str(Path.home()/'ThirdHand/UIEAclub_ThirdHand_VLA')))
        config=VisionConfig.from_yaml(live/'skills/manipulation/bottlegrasp/configs/vision.yaml')
        runtime=bridge.UnifiedVisionRuntime(config,backend,projection=Projection(transform))
        return runtime,frame(backend.mask)
    def test_calibrated_upright_rejects_nonhorizontal_table(self):
        runtime,f=self.runtime(np.eye(4))
        decision=runtime.process_frame(f)
        reasons=[reason for track in decision.tracks for reason in track.blockers]
        self.assertTrue(any('table_plane' in r for r in reasons),reasons)
    def test_camera_only_mode_keeps_existing_geometry(self):
        runtime,f=self.runtime(None)
        decision=runtime.process_frame(f)
        self.assertEqual(len(decision.tracks),1)
        self.assertFalse(any('table_plane' in r for track in decision.tracks for r in track.blockers))
    def test_unapproved_projection_does_not_supply_directions(self):
        runtime,f=self.runtime(np.eye(4))
        runtime.projection.projection_allowed=False
        decision=runtime.process_frame(f)
        self.assertEqual(len(decision.tracks),1)
        self.assertFalse(any('table_plane' in r for track in decision.tracks for r in track.blockers))

if __name__=='__main__':unittest.main()
