"""Motion must invalidate masks without losing the selected object's identity."""
import os
from pathlib import Path
from dataclasses import replace
from types import SimpleNamespace
import unittest

import numpy as np
from thirdhand_va.common.config import VisionConfig
from thirdhand_va.vision.perception.interfaces import RawCandidate
from thirdhand_va.vision.visualization.overlay import render_overlay, RenderMetrics
from camera_bridge_with_frames import UnifiedVisionRuntime

ROOT = Path(os.environ['THIRDHAND_LIVE_ROOT'])

class Backend:
    def __init__(self):
        self.resets = 0
        self.calls = 0
        self.visible = True
        self.mask = np.zeros((120, 180), bool)
        self.mask[25:110, 65:100] = True
    def reset_tracking(self):
        self.resets += 1
    def infer(self, rgb):
        self.calls += 1
        if not self.visible:
            return ()
        return (RawCandidate(detection_id=1, prompt_label='bottle', score=.99,
            bbox_xyxy=(65,25,100,110), mask=self.mask,
            descriptor=np.array([1.,0.,0.,0.], np.float32)),)

class MotionTests(unittest.TestCase):
    def setUp(self):
        self.backend = Backend()
        self.runtime = UnifiedVisionRuntime(VisionConfig.from_yaml(
            ROOT/'skills/manipulation/bottlegrasp/configs/vision.yaml'), self.backend)
        self.stamp = 1_000_000_000
        for _ in range(3):
            self.decision = self.runtime.process_frame(self.frame())
        self.assertTrue(self.runtime.select_target(1, 'motion-test'))
    def frame(self):
        self.stamp += 10_000_000
        return SimpleNamespace(sequence=self.stamp//10_000_000, monotonic_ns=self.stamp,
            camera_serial='test', rgb=np.zeros((120,180,3), np.uint8),
            depth_m=np.full((120,180), .4, np.float32),
            xyz_camera_m=np.tile(np.array([0.,0.,.4],np.float32), (120,180,1)))
    def state(self, stationary=True, x=.2):
        self.stamp += 10_000_000
        return {'type':'arm_state','connected':True,'healthy':True,'stationary':stationary,
            'pose_frame':'robot_flange','observed_monotonic_ns':self.stamp,
            'flange_position_m':[x,0,.2], 'flange_euler_rad':[0,0,0], 'joints_deg':[0]*6}
    def update(self, message):
        update = getattr(self.runtime, 'update_robot_state', None)
        self.assertTrue(callable(update), 'arm feedback must reach the motion tracking guard')
        update(message)
    def test_motion_hides_old_masks_and_starts_a_new_epoch(self):
        self.update(self.state())
        calls = self.backend.calls
        self.update(self.state(False))
        self.backend.visible = False
        decision = self.runtime.process_frame(self.frame())
        self.assertGreater(decision.motion_epoch, 0)
        self.assertFalse(any(t.state == 'confirmed' for t in decision.tracks))
        self.assertEqual(self.backend.calls, calls + 1)
        overlay = render_overlay(np.zeros((120,180,3),np.uint8), decision, RenderMetrics(5.,100.))
        self.assertFalse(np.any(overlay.image[80:110,60:110]))
        self.assertGreater(self.backend.resets, 0)
    def test_terminal_pose_jump_is_detected_even_without_moving_feedback(self):
        self.update(self.state())
        self.update(self.state(x=.21))
        self.backend.visible = False
        decision = self.runtime.process_frame(self.frame())
        self.assertFalse(any(t.state == 'confirmed' for t in decision.tracks))
        self.assertGreater(decision.motion_epoch, 0)
    def test_half_degree_terminal_yaw_also_resets_segmentation(self):
        self.update(self.state())
        state = self.state()
        state['flange_euler_rad'] = [0, 0, np.pi/360]
        self.update(state)
        self.backend.visible = False
        self.assertGreater(self.runtime.process_frame(self.frame()).motion_epoch, 0)
    def test_velocity_only_stationary_rejection_does_not_reset_static_camera_masks(self):
        self.update(self.state())
        self.update({**self.state(False), 'motion_active':False, 'feedback_invalidated':False})
        self.assertEqual(self.runtime.process_frame(self.frame()).motion_epoch, 0)
    def test_explicit_stale_invalidation_still_resets_camera_tracking(self):
        state = {**self.state(), 'motion_active':False, 'feedback_invalidated':False}
        self.update(state)
        self.update({**state, 'stationary':False, 'feedback_invalidated':True})
        self.assertGreater(self.runtime.process_frame(self.frame()).motion_epoch, 0)
    def test_settled_motion_reseeds_tracking_and_keeps_selected_id(self):
        self.update(self.state())
        self.update(self.state(False))
        self.runtime.process_frame(self.frame())
        for _ in range(3):
            self.update(self.state())
        decision = self.runtime.process_frame(self.frame())
        self.assertEqual(decision.selected_stable_id, 1)
        self.assertTrue(any(t.stable_id == 1 and t.state == 'confirmed' for t in decision.tracks))
        self.assertGreaterEqual(self.backend.resets, 2)
    def test_stale_feedback_invalidation_also_hides_tracking(self):
        state = self.state()
        self.update(state)
        self.update({**state, 'stationary':False})
        self.backend.visible = False
        self.assertFalse(any(t.state == 'confirmed' for t in self.runtime.process_frame(self.frame()).tracks))
    def test_similar_bottle_cannot_replace_depthless_selected_track_during_motion(self):
        self.update(self.state())
        self.update(self.state(False))
        self.backend.mask[:] = False
        self.backend.mask[25:110, 135:170] = True
        decision = self.runtime.process_frame(self.frame())
        self.assertFalse(any(t.stable_id == 1 and t.state == 'confirmed' for t in decision.tracks))
    def test_depthless_identity_cannot_reappear_after_a_motion_occlusion(self):
        self.update(self.state())
        self.update(self.state(False))
        self.backend.visible = False
        self.runtime.process_frame(self.frame())
        self.backend.visible = True
        for _ in range(3):
            self.update(self.state())
        decision = self.runtime.process_frame(self.frame())
        self.assertFalse(any(t.stable_id == 1 and t.state == 'confirmed' for t in decision.tracks))
    def test_two_plausible_depthless_matches_do_not_choose_one_arbitrarily(self):
        self.update(self.state())
        self.update(self.state(False))
        infer = self.backend.infer
        def ambiguous(rgb):
            first = infer(rgb)[0]
            shifted = np.roll(first.mask, 8, axis=1)
            return (first, replace(first, detection_id=2, bbox_xyxy=(73,25,108,110), mask=shifted))
        self.backend.infer = ambiguous
        decision = self.runtime.process_frame(self.frame())
        self.assertFalse(any(t.stable_id == 1 and t.state == 'confirmed' for t in decision.tracks))
    def test_zero_depth_cannot_create_a_reserved_base_anchor(self):
        runtime = UnifiedVisionRuntime(self.runtime.config, Backend(), projection=SimpleNamespace(
            snapshot_for_frame=lambda *args, **kwargs: SimpleNamespace(matrix_4x4=np.eye(4))))
        for _ in range(3):
            frame = self.frame()
            frame.depth_m[:] = 0
            frame.xyz_camera_m[:] = 0
            runtime.process_frame(frame)
        self.assertTrue(runtime.select_target(1, 'zero-depth'))
        self.assertFalse(runtime.pipeline.tracker.reserved_world_anchor_available)
    def test_lost_selected_track_is_not_painted_over_the_live_image(self):
        track = replace(self.decision.tracks[0], state='lost')
        decision = replace(self.decision, tracks=(track,))
        rgb = np.zeros((120,180,3), np.uint8)
        overlay = render_overlay(rgb, decision, RenderMetrics(5.,100.))
        self.assertFalse(np.any(overlay.image[80:110, 60:110]))

if __name__ == '__main__':
    unittest.main()
