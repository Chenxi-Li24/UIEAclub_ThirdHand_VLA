"""Reseeding may restore an anchored identity, never guess a bottle."""
from types import SimpleNamespace
import unittest
import numpy as np

from thirdhand_va.vision.tracking.stable_ids import StableTrackManager
from thirdhand_va.vision.tracking.norfair_adapter import Association, NorfairTrackerAdapter
from camera_bridge_with_frames import attach_depth_evidence


def candidate(i=0, x=5, descriptor=(1., 0.)):
    mask = np.zeros((40, 50), bool)
    mask[5:35, x:x+10] = True
    return SimpleNamespace(detection_id=i, mask=mask, authorized=True, reasons=(), score=.99,
                           descriptor=np.array(descriptor, np.float32))


class Adapter:
    max_point_distance_m = .08
    max_center_distance_px = 120
    backend = 10
    def update(self, candidates, **kwargs):
        return tuple(Association(self.backend+i, c) for i, c in enumerate(candidates))


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.adapter = Adapter()
        self.manager = StableTrackManager(adapter=self.adapter, confirmation_hits=3, lost_timeout_ms=2000)
        self.stamp = 0
        self.original = candidate()
        for _ in range(3): self.update((self.original,))
        self.assertTrue(self.manager.reserve(1, 'selected'))
        self.stamp += 3_000_000_000
        self.update((), moving=True)
        self.adapter.backend = 20
    def update(self, candidates, moving=False, points=None, stamp=None):
        self.stamp = stamp if stamp is not None else self.stamp+10_000_000
        points = points if points is not None else {c.detection_id:(.3,0,.2) for c in candidates}
        return self.manager.update(candidates, now_ns=self.stamp, camera_moving=moving,
                                   world_points=points, camera_points=points)
    def selected(self, tracks):
        return next(t for t in tracks if t.stable_id == 1)
    def test_unique_anchored_bottle_recovers_after_three_fresh_observations(self):
        fresh = candidate(x=30)
        for _ in range(2):
            self.assertNotEqual(self.selected(self.update((fresh,))).state, 'confirmed')
        tracks = self.update((fresh,))
        self.assertEqual(self.selected(tracks).state, 'confirmed')
        self.assertEqual(self.selected(tracks).backend_track_id, 20)
        self.assertEqual(sum(t.stable_id == 1 for t in tracks), 1)
        self.assertEqual(self.manager.reservation, (1, 'selected'))
    def test_wrong_appearance_far_point_moving_and_ambiguity_never_recover(self):
        for candidates, moving, points in [
            ((candidate(x=30, descriptor=(0.,1.)),), False, None),
            ((candidate(x=30),), False, {0:(.36,0,.2)}),
            ((candidate(x=30),), True, None),
            ((candidate(x=30),candidate(1,x=10)), False, {0:(.30,0,.2),1:(.301,0,.2)}),
        ]:
            for _ in range(5): tracks = self.update(candidates, moving, points)
            self.assertNotEqual(self.selected(tracks).state, 'confirmed')
    def test_replayed_timestamp_does_not_confirm_recovery(self):
        fresh = candidate(x=30)
        stamp = self.stamp+1
        for _ in range(5): tracks = self.update((fresh,), stamp=stamp)
        self.assertNotEqual(self.selected(tracks).state, 'confirmed')
    def test_depthless_motion_gap_requires_explicit_reselection(self):
        self.manager._reserved_world_anchor = None
        self.manager._reserved_continuity_lost = True
        for _ in range(5): tracks = self.update((candidate(x=30),), points={})
        self.assertNotEqual(self.selected(tracks).state, 'confirmed')
        self.assertIn('target_reselection_required', self.selected(tracks).blockers)
    def test_existing_other_bottle_is_not_stolen(self):
        self.manager._reserved_backend_ids.add(20)
        for _ in range(5): tracks = self.update((candidate(x=30),))
        self.assertNotEqual(self.selected(tracks).state, 'confirmed')
    def test_reseeded_neighbor_bottle_cannot_take_selected_identity(self):
        self.manager = StableTrackManager(adapter=self.adapter, confirmation_hits=3, lost_timeout_ms=2000)
        self.adapter.backend = 10
        bottles = (candidate(), candidate(1,x=30))
        for _ in range(3): self.update(bottles, points={0:(.3,0,.2),1:(.335,0,.2)})
        self.assertTrue(self.manager.reserve(1,'two-bottles'))
        self.stamp += 3_000_000_000
        self.update((), moving=True)
        self.adapter.backend = 20
        for _ in range(5): tracks = self.update((candidate(1,x=30),), points={1:(.335,0,.2)})
        self.assertNotEqual(self.selected(tracks).state, 'confirmed')
    def test_nonfinite_appearance_cannot_confirm_recovery(self):
        for _ in range(5): tracks = self.update((candidate(x=30, descriptor=(np.nan,0.)),))
        self.assertNotEqual(self.selected(tracks).state, 'confirmed')
    def test_observations_separated_by_long_gaps_are_not_consecutive(self):
        for _ in range(5):
            self.stamp += 2_000_000_000
            tracks = self.update((candidate(x=30),))
        self.assertNotEqual(self.selected(tracks).state, 'confirmed')
    def test_real_norfair_expiry_recovers_the_original_selected_id(self):
        self.adapter = NorfairTrackerAdapter(max_center_distance_px=120, max_point_distance_m=.08)
        self.manager = StableTrackManager(adapter=self.adapter, confirmation_hits=3, lost_timeout_ms=2000)
        for _ in range(3): tracks = self.update((candidate(),))
        original_backend = tracks[0].backend_track_id
        self.assertTrue(self.manager.reserve(1, 'real-expiry'))
        for _ in range(40):
            self.stamp += 100_000_000
            self.update((), moving=True)
        for _ in range(3): tracks = self.update((candidate(x=30),))
        self.assertEqual(self.selected(tracks).state, 'confirmed')
        self.assertNotEqual(self.selected(tracks).backend_track_id, original_backend)


class EvidenceIdentityTests(unittest.TestCase):
    def test_recycled_detection_id_never_attaches_new_depth_to_lost_track(self):
        old = SimpleNamespace(backend_track_id=10, candidate=candidate(), state='lost')
        new = SimpleNamespace(backend_track_id=20, candidate=candidate(x=30), state='confirmed')
        frame = SimpleNamespace(sequence=7, monotonic_ns=1, camera_serial='test',
            depth_m=np.full((40,50), .4), xyz_camera_m=np.tile([0.,0.,.4], (40,50,1)))
        config = SimpleNamespace(min_depth_m=.1, max_depth_m=1., min_depth_points=250, min_depth_ratio=.05)
        event = {'targets':[{'stable_id':1,'backend_track_id':10,'detection_id':0},
                            {'stable_id':2,'backend_track_id':20,'detection_id':0}]}
        attach_depth_evidence(event, SimpleNamespace(tracks=(old,new)), frame, config)
        lost, fresh = event['targets']
        self.assertIsNone(lost['depth_m'])
        self.assertEqual(lost['valid_depth_points'], 0)
        self.assertEqual(lost['raw_valid_depth_points'], 0)
        self.assertAlmostEqual(fresh['depth_m'], .4)


if __name__ == '__main__': unittest.main()
