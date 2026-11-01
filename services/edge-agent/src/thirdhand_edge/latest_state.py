"""Latest-only measured state. No outbox, command, SDK connection or media queue."""
import base64
import json
import threading
import time

from .telemetry import normalize_robot_state
from .upload import TelemetryUploadClient


def make_report(frame, context, *, now_ns=None, wall_ms=None, versions=None):
    now_ns = time.monotonic_ns() if now_ns is None else now_ns
    wall_ms = int(time.time() * 1000) if wall_ms is None else wall_ms
    message = frame.get('message', {})
    connection = message.get('type') == 'connection' and type(message.get('connected')) is bool
    producer = frame.get('sourceMonotonicNs') if connection else message.get('producer_monotonic_ns')
    sequence = frame.get('sequence')
    if (frame.get('type') != 'robot_event' or not (message.get('type') == 'robot_state' or connection) or
        not context.get('executorEpoch') or frame.get('executorEpoch') != context['executorEpoch'] or
        type(producer) is not int or not 0 < producer <= now_ns or
        type(sequence) is not int or sequence < 1):
        raise ValueError('Current measured event required')
    age = (now_ns - producer) / 1_000_000
    if age > 3000:
        raise ValueError('Expired source state')
    if connection:
        # An actual connection event carries no joint, gripper or moving values.
        message = {'type': 'robot_state', 'connected': message['connected'], 'captured_at': frame['receivedAt']}
    sample = normalize_robot_state(message, monotonic_ns=now_ns, received_at=frame.get('receivedAt'), versions=versions)
    # Raw events and targets stay in archival storage, not the live response.
    sample['extra'].pop('rawState', None)
    sample['extra'].pop('target', None)
    sample['extra']['sourceMode'] = frame.get('sourceMode', 'unknown')
    for field in ('sdkConnected', 'moving'):
        if not sample['fieldAvailability'][field]:
            sample[field] = None
    return {'schema': 1, 'purpose': 'latest_state', 'context': context,
            'sequence': sequence, 'producerMonotonicNs': producer,
            'sourceAgeMs': age, 'issuedAt': wall_ms, 'sample': sample}


class LatestStateClient(TelemetryUploadClient):
    endpoint = '/edge/v1/state'
    timeout_seconds = 2
    maximum_bytes = 24000

    def send(self, report):
        payload = json.dumps(report, allow_nan=False, separators=(',', ':')).encode()
        encode = lambda value: base64.urlsafe_b64encode(value).decode().rstrip('=')
        result = self._post({'payloadBase64url': encode(payload), 'signatureBase64url': encode(self._key.sign(payload))})
        if result != {'accepted': True, 'sequence': report['sequence']}:
            raise ValueError('State ACK mismatch')


def publish_latest(robot, client, *, context_path, device_id, boot_id, versions=None):
    # One reader continually replaces a one-item slot even while HTTP is delayed.
    # Stream/network failure is contained here; it must not restart control.
    lock, stopping = threading.Lock(), threading.Event()
    latest = [None]
    def read():
        while not stopping.is_set():
            try:
                for frame in robot.iter_events():
                    if stopping.is_set():
                        return
                    with lock:
                        if frame.get('type') == 'source_snapshot':
                            latest[0] = None
                        elif frame.get('message', {}).get('type') in ('robot_state', 'connection'):
                            latest[0] = frame
            except Exception:
                with lock:
                    latest[0] = None
                stopping.wait(1)
    reader = threading.Thread(target=read, daemon=True, name='latest-state-reader')
    reader.start()
    last_sent = None
    try:
        while not stopping.wait(0.2):
            try:
                context = json.loads(context_path.read_text(encoding='utf-8'))
                if context.get('deviceId') != device_id or context.get('bootId') != boot_id:
                    continue
                with lock:
                    frame = latest[0]
                if frame is None:
                    continue
                report = make_report(frame, context, versions=versions)
                key = (context.get('connectionId'), report['sequence'])
                if key == last_sent:
                    continue
                # Never retry an already attempted sample; the next measured
                # frame replaces it. Server also rejects repeat/out-of-order.
                last_sent = key
                client.send(report)
            except Exception:
                stopping.wait(1)
    finally:
        stopping.set()
        client.close()
        reader.join(timeout=0.1)  # bounded SSE read ends with process, no command
