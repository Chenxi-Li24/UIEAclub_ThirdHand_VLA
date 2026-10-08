from test_meituan_battery import module
from types import SimpleNamespace
import numpy as np
import pytest

def frame():
    return SimpleNamespace(rgb=np.zeros((20,20,3), np.uint8), sequence=7)

def test_mailbox_only_keeps_latest_pending_request_and_uses_injected_model():
    m=module()
    assert hasattr(m,"BatteryMailbox"), "shared model request mailbox missing"
    events=[]
    models=object()
    def infer(actual,rgb,sequence,params):
        assert actual is models
        return {"frameId":sequence,"detections":[],"jpeg":b"jpeg","elapsedMs":1,"parameters":params}
    box=m.BatteryMailbox(events.append,infer=infer)
    box.submit("session","one",{})
    box.submit("session","two",{"prompt":"red battery"})
    box.process(frame(),models)
    results=[e for e in events if e["type"]=="meituan_result"]
    assert len(results)==1 and results[0]["requestId"]=="two"
    assert results[0]["parameters"]["prompt"]=="red battery"
    box.process(frame(),models)
    assert len([e for e in events if e["type"]=="meituan_result"])==1

def test_cancel_during_inference_suppresses_result_and_does_not_submit_more():
    m=module()
    assert hasattr(m,"BatteryMailbox"), "shared model request mailbox missing"
    events=[]
    def infer(*args):
        box.cancel("session")
        return {"frameId":7,"detections":[],"jpeg":b"jpeg","elapsedMs":1,"parameters":{}}
    box=m.BatteryMailbox(events.append,infer=infer)
    box.submit("session","one",{})
    box.process(frame(),object())
    assert not [e for e in events if e["type"]=="meituan_result"]
    assert any(e["type"]=="meituan_log" for e in events)

def test_inference_failure_reports_full_trace_without_raising_into_bottle_loop():
    m=module()
    assert hasattr(m,"BatteryMailbox"), "shared model request mailbox missing"
    events=[]
    def infer(*args):
        raise RuntimeError("CUDA out of memory test")
    box=m.BatteryMailbox(events.append,infer=infer)
    box.submit("session","broken",{})
    box.process(frame(),object())
    error=next(e for e in events if e["type"]=="meituan_error")
    assert "CUDA out of memory test" in error["error"]["stack"]
    assert error["frameId"]==7 and error["requestId"]=="broken"
    assert not [e for e in events if e["type"]=="meituan_result"]
    box.process(frame(),object())
    assert len([e for e in events if e["type"]=="meituan_error"])==1

def test_invalid_id_or_parameters_rejected_before_queueing():
    m=module()
    assert hasattr(m,"BatteryMailbox"), "shared model request mailbox missing"
    box=m.BatteryMailbox(lambda e:None)
    with pytest.raises(ValueError):
        box.submit("","r",{})
    with pytest.raises(ValueError):
        box.submit("s","r",{"boxThreshold":0})
