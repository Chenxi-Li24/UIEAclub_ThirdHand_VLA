"""Same-frame arm evidence for palm ownership; never a motion controller."""
from dataclasses import dataclass
import hashlib
import json
import math

from .config import APP_ROOT, resolve_project_path
from .face_person_selector import overlap


@dataclass(frozen=True)
class PersonPose:
    x: float
    y: float
    w: float
    h: float
    score: float
    keypoints: tuple


class PoseDetector:
    def __init__(self, options, *, model=None):
        self.device = options.get('device', 'cpu')
        self.imgsz = int(options.get('imgsz', 640))
        if model is None:
            manifest = json.loads((APP_ROOT / 'configs' / 'ok-pose-model.json').read_text())
            path = resolve_project_path(options.get('pose_model_path', manifest['path']))
            if not path.is_file():
                raise RuntimeError('Palm pose weights missing; run apps/dummy/apps/prepare_ok_model.py')
            with path.open('rb') as source:
                digest = hashlib.file_digest(source, 'sha256').hexdigest()
            if path.stat().st_size != manifest['bytes'] or digest != manifest['sha256']:
                raise ValueError('Palm pose model hash/size mismatch')
            from ultralytics import YOLO
            model = YOLO(str(path))
        if getattr(model, 'task', None) != 'pose':
            raise ValueError('Palm ownership requires a person pose model')
        self.model = model

    def detect(self, frame):
        results = self.model.predict(frame, conf=.25, imgsz=self.imgsz,
                                     device=self.device, verbose=False)
        poses = []
        for result in results:
            if result.boxes is None or result.keypoints is None:
                continue
            boxes = result.boxes.xyxy.cpu().tolist()
            scores = result.boxes.conf.cpu().tolist()
            points = result.keypoints.data.cpu().tolist()
            for box, score, skeleton in zip(boxes, scores, points):
                x1, y1, x2, y2 = map(float, box)
                if (len(skeleton) == 17 and all(len(p) == 3 for p in skeleton)
                        and all(math.isfinite(v) for v in (*box, score))
                        and x2 > x1 and y2 > y1):
                    poses.append(PersonPose(x1, y1, x2-x1, y2-y1, float(score),
                                            tuple(tuple(map(float, p)) for p in skeleton)))
        return poses


class PoseOwnerMatcher:
    def __init__(self, options):
        self.min_confidence = float(options.get('pose_keypoint_min_confidence', .35))
        self.min_iou = float(options.get('pose_body_min_iou', .45))
        self.iou_margin = float(options.get('pose_body_iou_margin', .15))
        self.hand_padding = float(options.get('wrist_hand_padding', .35))
        self.evidence = []

    def owners(self, hand, poses, bodies):
        self.evidence = []
        owners = {}
        for pose in poses:
            if (pose.w <= 0 or pose.h <= 0 or not all(math.isfinite(v)
                    for v in (pose.x, pose.y, pose.w, pose.h, pose.score))):
                continue
            supported_arms = []
            for side, indices in (('left', (5, 7, 9)), ('right', (6, 8, 10))):
                if len(pose.keypoints) != 17:
                    continue
                arm = [pose.keypoints[i] for i in indices]
                if any(len(p) != 3 or not all(math.isfinite(v) for v in p)
                       or p[2] < self.min_confidence for p in arm):
                    continue
                shoulder, elbow, wrist = arm
                # The wrist must touch the hand region, supported by its own
                # elbow/shoulder chain. A hand inside another body is insufficient.
                pad_x, pad_y = self.hand_padding*hand.w, self.hand_padding*hand.h
                if not (hand.x-pad_x <= wrist[0] <= hand.x+hand.w+pad_x
                        and hand.y-pad_y <= wrist[1] <= hand.y+hand.h+pad_y):
                    continue
                if not (pose.x <= shoulder[0] <= pose.x+pose.w
                        and pose.y <= shoulder[1] <= pose.y+pose.h):
                    continue
                lengths = [math.hypot(a[0]-b[0], a[1]-b[1]) for a, b in ((shoulder, elbow), (elbow, wrist))]
                if not all(2 <= length <= math.hypot(pose.w, pose.h) for length in lengths):
                    continue
                supported_arms.append((side, arm))
            if not supported_arms:
                continue
            ranked = sorted(((overlap(pose, b), b) for b in bodies), key=lambda x: x[0], reverse=True)
            if (not ranked or ranked[0][0] < self.min_iou
                    or len(ranked) > 1 and ranked[0][0]-ranked[1][0] < self.iou_margin):
                # A competing, wrist-compatible arm cannot be silently discarded.
                self.evidence.append({'person_track_id': None, 'reason': 'pose_body_ambiguous'})
                return []
            body = ranked[0][1]
            for side, arm in supported_arms:
                owners[body.track_id] = body
                self.evidence.append({'person_track_id': body.track_id, 'side': side,
                                      'body_iou': ranked[0][0], 'arm_xy': [list(p[:2]) for p in arm],
                                      'confidence': min(p[2] for p in arm)})
        return list(owners.values())
