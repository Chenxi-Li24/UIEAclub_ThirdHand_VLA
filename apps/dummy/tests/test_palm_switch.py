from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from dummy.ok_gesture import GestureFrame, HandGesture, HagridDetector, OkSwitch
from dummy.config import load_config
from test_ok_switch import scene, poses


def test_detector_filters_palm_by_name_and_does_not_accept_ok_or_stop():
    calls = []
    boxes = SimpleNamespace(xyxy=np.array([[10, 20, 30, 50]]*3),
                            conf=np.array([.95]*3), cls=np.array([3, 7, 9]))
    def predict(_frame, **options):
        calls.append(options)
        return [SimpleNamespace(boxes=boxes)]
    model = SimpleNamespace(names={3: 'ok', 7: 'palm', 9: 'stop'}, predict=predict)
    hands = HagridDetector({}, model=model).detect(np.zeros((80, 80, 3), dtype=np.uint8))
    assert hands == [HandGesture(10, 20, 20, 30, .95, 'palm')]
    assert calls[0]['classes'] == [7]


def test_model_without_palm_label_is_rejected():
    with pytest.raises(ValueError, match='palm'):
        HagridDetector({}, model=SimpleNamespace(names={0: 'ok'}))


@pytest.mark.parametrize('label,expected', [('palm', 2), ('ok', None)])
def test_only_palm_confirms_selection_with_existing_owner_and_hold_rules(label, expected):
    faces, bodies = scene()
    switch = OkSwitch({})
    selected = None
    for sequence, stamp in enumerate([1., 1.2, 1.4, 1.6], 1):
        hand = HandGesture(430, 180, 20, 30, .95, label)
        result = GestureFrame(sequence, stamp, 0, (hand,), tuple(bodies), tuple(faces), 2.,
                              poses=poses(bodies))
        selected = switch.update(result, now=stamp+.01, bodies=bodies, faces=faces, epoch=0)
    assert selected == expected


def test_preview_labels_the_trigger_as_palm(monkeypatch):
    import dummy.person_follow.telemetry as telemetry
    texts = []
    original = telemetry.cv2.putText
    def put_text(image, text, *args, **kwargs):
        texts.append(text)
        return original(image, text, *args, **kwargs)
    monkeypatch.setattr(telemetry.cv2, 'putText', put_text)
    state = {'status': 'locked', 'mode': 'HOLDING', 'control_source': 'FACE', 'frame_id': 1,
             'target': {'found': False, 'kind': 'face_person_face'},
             'ok_switch': {'reason': 'confirming_ok', 'progress': .5, 'person_track_id': 2,
                           'hands': [{'x': 30, 'y': 90, 'w': 20, 'h': 30, 'score': .95,
                                      'label': 'palm', 'person_track_id': 2}]}}
    assert telemetry.encode_frame(np.zeros((240, 320, 3), dtype=np.uint8), state)
    assert any(text.startswith('PALM ') for text in texts)
    assert any(text.startswith('PALM:') for text in texts)
    assert not any(text.startswith('OK') for text in texts)


def test_formal_config_accepts_point65_palm_but_rejects_lower_score():
    boxes = SimpleNamespace(xyxy=np.array([[10, 20, 30, 50]]*2),
                            conf=np.array([.65, .649]), cls=np.array([20, 20]))
    model = SimpleNamespace(names={20: 'palm'},
                            predict=lambda *_args, **_kwargs: [SimpleNamespace(boxes=boxes)])
    detector = HagridDetector(load_config()['ok_switch'], model=model)
    assert detector.detect(np.zeros((80, 80, 3), dtype=np.uint8)) == [
        HandGesture(10, 20, 20, 30, .65, 'palm')]


@pytest.mark.parametrize('stamps,expected', [
    ([1., 1.1, 1.11], [None, None, 2]),
    ([1., 1.05, 1.099, 1.1], [None, None, None, 2]),
])
def test_formal_config_requires_three_frames_and_point1_second_hold(stamps, expected):
    faces, bodies = scene()
    switch = OkSwitch(load_config()['ok_switch'])
    selected = []
    for sequence, stamp in enumerate(stamps, 1):
        result = GestureFrame(sequence, stamp, 0, (HandGesture(430, 180, 20, 30, .95, 'palm'),),
                              tuple(bodies), tuple(faces), 2., poses=poses(bodies))
        selected.append(switch.update(result, now=stamp+.01, bodies=bodies, faces=faces, epoch=0))
    assert selected == expected


@pytest.mark.parametrize('pattern,expected', [
    ('VV-V', [None, None, None, 2]),
    ('V-VV', [None, None, None, 2]),
    ('VV--V', [None]*5),
    ('V-V-VV', [None]*5+[2]),
    ('V--VVV', [None]*5+[2]),
])
def test_recent_four_results_require_three_valid_same_person_palms(pattern, expected):
    faces, bodies = scene()
    switch = OkSwitch(load_config()['ok_switch'])
    selected = []
    for sequence, value in enumerate(pattern, 1):
        stamp = 1.+(sequence-1)*.05
        hands = (HandGesture(430, 180, 20, 30, .95, 'palm'),) if value == 'V' else ()
        result = GestureFrame(sequence, stamp, 0, hands, tuple(bodies), tuple(faces), 2.,
                              poses=poses(bodies))
        selected.append(switch.update(result, now=stamp+.001, bodies=bodies, faces=faces, epoch=0))
    assert selected == expected


def test_three_previous_palms_cannot_trigger_on_a_missing_latest_result():
    faces, bodies = scene()
    switch = OkSwitch({'hold_s': .1, 'confirmation_window_frames': 4})
    for sequence, stamp in enumerate([1., 1.02, 1.04, 1.12], 1):
        hands = () if sequence == 4 else (HandGesture(430, 180, 20, 30, .95, 'palm'),)
        result = GestureFrame(sequence, stamp, 0, hands, tuple(bodies), tuple(faces), 2., poses=poses(bodies))
        assert switch.update(result, now=stamp+.001, bodies=bodies, faces=faces, epoch=0) is None


def test_rolling_confirmation_cannot_mix_owners_or_count_duplicate_results():
    faces, bodies = scene()
    switch = OkSwitch({'hold_s': .1, 'confirmation_window_frames': 4})
    result = None
    for sequence, stamp, owner in [(1, 1., 2), (2, 1.05, 2), (3, 1.1, 1), (4, 1.15, 1)]:
        hand = HandGesture(430 if owner == 2 else 130, 180, 20, 30, .95, 'palm')
        result = GestureFrame(sequence, stamp, 0, (hand,), tuple(bodies), tuple(faces), 2., poses=poses(bodies))
        assert switch.update(result, now=stamp+.001, bodies=bodies, faces=faces, epoch=0) is None
    for stamp in [1.17, 1.2, 1.22]:
        assert switch.update(result, now=stamp, bodies=bodies, faces=faces, epoch=0) is None


def test_ambiguity_or_missing_body_clears_rolling_confirmation():
    from dataclasses import replace
    faces, bodies = scene()
    switch = OkSwitch({'hold_s': .1, 'confirmation_window_frames': 4})
    for sequence, stamp in [(1, 1.), (2, 1.05)]:
        result = GestureFrame(sequence, stamp, 0, (HandGesture(430, 180, 20, 30, .95, 'palm'),),
                              tuple(bodies), tuple(faces), 2., poses=poses(bodies))
        assert switch.update(result, now=stamp+.001, bodies=bodies, faces=faces, epoch=0) is None
    ambiguous = replace(result, frame_id=3, received_at=1.1, poses=())
    assert switch.update(ambiguous, now=1.101, bodies=bodies, faces=faces, epoch=0) is None
    assert switch.candidate is None
    valid = replace(result, frame_id=4, received_at=1.15)
    assert switch.update(valid, now=1.151, bodies=bodies, faces=faces, epoch=0) is None
    missing_body = replace(valid, frame_id=5, received_at=1.2, bodies=(), faces=(), hands=())
    assert switch.update(missing_body, now=1.201, bodies=[], faces=[], epoch=0) is None
    assert switch.candidate is None


@pytest.mark.parametrize('interruption', ['snapshot_body_missing', 'stale', 'gap', 'time_reversed', 'keyword'])
def test_uncertain_or_interrupted_result_clears_rolling_votes(interruption):
    from dataclasses import replace
    faces, bodies = scene()
    switch = OkSwitch(load_config()['ok_switch'])
    for sequence, stamp in [(1, 1.), (2, 1.05)]:
        result = GestureFrame(sequence, stamp, 0, (HandGesture(430, 180, 20, 30, .95, 'palm'),),
                              tuple(bodies), tuple(faces), 2., poses=poses(bodies))
        assert switch.update(result, now=stamp+.001, bodies=bodies, faces=faces, epoch=0) is None
    interrupted = replace(result, frame_id=3, received_at=1.1, hands=())
    now = 1.101
    if interruption == 'snapshot_body_missing':
        interrupted = replace(interrupted, bodies=(), faces=())
    elif interruption == 'stale':
        now = 1.7
    elif interruption == 'gap':
        interrupted = replace(interrupted, received_at=1.5)
        now = 1.501
    elif interruption == 'time_reversed':
        interrupted = replace(interrupted, received_at=1.04)
        now = 1.041
    assert switch.update(interrupted, now=now, bodies=bodies, faces=faces, epoch=0,
                         allowed=interruption != 'keyword') is None
    assert switch.candidate is None
    assert not switch.confirmation_results
