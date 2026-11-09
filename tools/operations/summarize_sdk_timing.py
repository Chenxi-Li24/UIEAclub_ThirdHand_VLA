"""Summarize allowlisted SDK timing JSONL; never echo arbitrary log text.

Inputs must be extracted sdk_segment_timing records, not HTTP payload captures.
Durations within each process use monotonic clocks. Cross-host wall deltas are
labelled estimates and are NOT proof of one-way network latency.
"""
import argparse
import json
import math
from pathlib import Path
import re
import statistics

PAIRS = {
    'cloud': {'dispatch_queue_ms': ('queued', 'dequeued'), 'principal_ms': ('dequeued', 'principal'),
              'readiness_ms': ('principal', 'readiness'), 'repository_ms': ('readiness', 'repository'),
              'signing_ms': ('repository', 'signed'), 'relay_dispatch_ms': ('signed', 'dispatched'),
              'signed_to_ack_ms': ('signed', 'ack')},
    'relay': {'registration_ms': ('queued', 'registered'), 'write_callback_ms': ('dispatched', 'write_callback'),
              'dispatch_to_ack_ms': ('dispatched', 'ack')},
    'edge': {'task_schedule_ms': ('received', 'task_started'), 'verification_ms': ('task_started', 'verified'),
             'lease_lock_ms': ('lock_wait', 'lock_acquired'), 'local_request_ms': ('lock_acquired', 'local_reply'),
             'reply_write_ms': ('local_reply', 'reply_sent'), 'edge_processing_ms': ('received', 'reply_sent')},
}


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def summarize(lines):
    traces, uncorrelated, ignored, duplicates = {}, 0, 0, 0
    for line in lines:
        try:
            row = json.loads(line)
            if row.get('component') != 'sdk_segment_timing' or row.get('segment') not in PAIRS:
                ignored += 1
                continue
            trace = row.get('trace')
            if trace is None:
                uncorrelated += 1
                continue
            if not isinstance(trace, str) or not re.fullmatch('[a-f0-9]{64}', trace) or not isinstance(row.get('marks'), dict):
                ignored += 1
                continue
            group = traces.setdefault(trace, {})
            if row['segment'] in group:
                duplicates += 1
                continue
            group[row['segment']] = row
        except (ValueError, TypeError, AttributeError):
            ignored += 1
    values, complete, outcomes = {}, 0, {}
    def add(key, value):
        values.setdefault(key, []).append(value)
    for group in traces.values():
        complete += int(set(group) == set(PAIRS))
        for segment, row in group.items():
            outcome = row.get('outcome') if row.get('outcome') in ('active', 'rejected', 'failed', 'unknown') else 'unknown'
            key = segment + ':' + outcome
            outcomes[key] = outcomes.get(key, 0) + 1
            for label, (start, end) in PAIRS[segment].items():
                a, b = row['marks'].get(start), row['marks'].get(end)
                if number(a) and number(b) and 0 <= a <= b <= 60000:
                    add(label, b - a)
        relay, edge = group.get('relay'), group.get('edge')
        if relay and edge:
            # Includes network + TLS/proxy/socket queues and any clock offset.
            start, sent = relay.get('startedAtMs'), relay['marks'].get('dispatched')
            received = edge.get('startedAtMs')
            if all(number(v) for v in (start, sent, received)):
                add('downstream_wall_estimate_ms_not_one_way_proof', received - start - sent)
    stats = {key: {'samples': len(v), 'p50': round(statistics.median(v), 3),
                   'p95': round(sorted(v)[math.ceil(len(v)*.95)-1], 3), 'max': round(max(v), 3)}
             for key, v in values.items()}
    return dict(correlatedTraces=len(traces), completeTraces=complete,
                incompleteTraces=len(traces)-complete, uncorrelatedRecords=uncorrelated,
                ignoredRecords=ignored, duplicateSegments=duplicates, outcomes=outcomes, durations=stats,
                warning='Wall-clock estimates include clock offset and unmeasured queues; missing phases are not zero.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('inputs', nargs='+', type=Path)
    args = parser.parse_args()
    def lines():
        for path in args.inputs:
            with path.open(encoding='utf-8') as stream:
                yield from stream
    print(json.dumps(summarize(lines()), ensure_ascii=False, indent=2))
