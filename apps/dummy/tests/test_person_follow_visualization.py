import sys
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from dummy.person_follow.visualization import render_overlay, dashboard_snapshot

def test_overlay_draws_identity_error_and_proposal_without_mutating_input():
    frame=np.zeros((480,640,3),dtype=np.uint8); original=frame.copy()
    state={"bbox_xyxy":[200,80,420,440],"center_px":[350,210],"track_id":7,"identity_id":"abc","identity_state":"LOCKED","confidence":.91,"latency_ms":14,"fps":22,"proposal":{"joints_deg":[0,.1,0,.2,0,0],"proposal_id":"p1"},"gateway":{"ok":True,"reason_code":"AUTHORIZED"},"verification":{"ok":True,"reason_code":"VERIFIED","improvement_px":8}}
    out=render_overlay(frame,state)
    assert np.array_equal(frame,original)
    assert np.count_nonzero(out)>100

def test_dashboard_snapshot_contains_all_debug_sections():
    value=dashboard_snapshot({}, now=2.0)
    assert set(value) >= {"vision","identity","control","gateway","verification","versions"}
