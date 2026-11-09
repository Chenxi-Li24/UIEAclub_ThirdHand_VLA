import importlib.util
import json
from pathlib import Path

spec = importlib.util.spec_from_file_location('timing_summary', Path(__file__).resolve().parents[3] / 'tools/operations/summarize_sdk_timing.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_correlates_segments_but_never_calls_clock_offset_network_latency():
    def row(segment, start, marks, trace='a'*64):
        return json.dumps(dict(component='sdk_segment_timing', segment=segment, trace=trace, startedAtMs=start, marks=marks, outcome='active', private='SECRET'))
    cloud = row('cloud', 1000, dict(queued=0, dequeued=1, principal=3, readiness=4, repository=8, signed=9, dispatched=10, ack=100))
    relay = row('relay', 1009, dict(queued=0, registered=1, dispatched=1, ack=91))
    edge = row('edge', 900, dict(received=0, task_started=1, verified=2, lock_wait=2, lock_acquired=5, local_reply=8, reply_sent=9))
    result = module.summarize([cloud, relay, edge, edge, 'not-json', row('edge', 900, {}, 'b'*64)])
    assert result['completeTraces'] == 1 and result['incompleteTraces'] == 1
    assert result['duplicateSegments'] == 1 and result['ignoredRecords'] == 1
    assert result['durations']['local_request_ms']['p50'] == 3
    assert result['durations']['downstream_wall_estimate_ms_not_one_way_proof']['p50'] == -110
    assert result['durations']['dispatch_to_ack_ms']['p50'] == 90
    assert 'SECRET' not in json.dumps(result)
