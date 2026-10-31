"""Immutable SQLite WAL upload buffer. ACK is accepted only with committed digest."""
import base64
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
import uuid


class OutboxCapacityError(RuntimeError):
    pass


class Outbox:
    STREAMS = {"robot_samples", "device_events", "command_events"}
    RESERVE_BYTES = 32768

    def __init__(self, path, *, device_id, boot_id, max_bytes=268435456):
        uuid.UUID(device_id)
        uuid.UUID(boot_id)
        if type(max_bytes) is not int or not 262144 <= max_bytes <= 17179869184:
            raise ValueError("Invalid outbox capacity")
        self.path, self.device_id, self.boot_id, self.max_bytes = Path(path), device_id, boot_id, max_bytes
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.is_symlink():
            raise ValueError("Outbox must not be a symlink")
        if not self.path.exists():
            descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(descriptor)
        self.db = sqlite3.connect(self.path, timeout=0.1, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA wal_autocheckpoint=100")
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS streams(device TEXT NOT NULL,boot TEXT NOT NULL,kind TEXT NOT NULL,next_seq INTEGER NOT NULL DEFAULT 0,next_batch INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(device,boot,kind));
          CREATE TABLE IF NOT EXISTS batches(id TEXT PRIMARY KEY,device TEXT NOT NULL,boot TEXT NOT NULL,kind TEXT NOT NULL,batch_seq INTEGER NOT NULL,first_seq INTEGER NOT NULL,last_seq INTEGER NOT NULL,digest TEXT NOT NULL,payload BLOB NOT NULL,acked_at INTEGER,UNIQUE(device,boot,kind,batch_seq));
          CREATE TABLE IF NOT EXISTS records(device TEXT NOT NULL,boot TEXT NOT NULL,kind TEXT NOT NULL,seq INTEGER NOT NULL,data TEXT NOT NULL,batch_id TEXT REFERENCES batches(id),PRIMARY KEY(device,boot,kind,seq));
          CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        """)
        row = self.db.execute("SELECT value FROM metadata WHERE key='alarm'").fetchone()
        self.alarm = row[0] if row else None
        for kind in self.STREAMS:
            self.db.execute("INSERT OR IGNORE INTO streams(device,boot,kind) VALUES(?,?,?)", (device_id, boot_id, kind))

    def _usage(self):
        return sum(path.stat().st_size for path in (self.path, Path(str(self.path) + "-wal"), Path(str(self.path) + "-shm")) if path.exists())

    def _capacity(self, addition):
        if self.alarm or self._usage() + addition + self.RESERVE_BYTES >= self.max_bytes:
            self.alarm = "OUTBOX_CAPACITY"
            try:
                self.db.execute("INSERT INTO metadata(key,value) VALUES('alarm',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (self.alarm,))
            except sqlite3.Error:
                pass
            raise OutboxCapacityError(self.alarm)

    def health(self):
        used = self._usage()
        return {"writable": self.alarm is None and used + self.RESERVE_BYTES < self.max_bytes, "alarm": self.alarm,
                "bytes": used, "limitBytes": self.max_bytes, "nearCapacity": used >= self.max_bytes * 0.8}

    def source_cursor(self):
        row = self.db.execute("SELECT value FROM metadata WHERE key=?", ("source_cursor:" + self.device_id + ":" + self.boot_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def append_sample(self, sample, *, source_cursor=None):
        return self.append_event("robot_samples", sample, source_cursor=source_cursor)

    def append_event(self, kind, value, *, source_cursor=None):
        if kind not in self.STREAMS or not isinstance(value, dict) or "sequence" in value:
            raise ValueError("Outbox assigns the source sequence")
        raw = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        if source_cursor is not None:
            if not isinstance(source_cursor, dict) or set(source_cursor) != {"executorEpoch", "sequence"} or type(source_cursor["sequence"]) is not int or source_cursor["sequence"] < 0:
                raise ValueError("Invalid source cursor")
            uuid.UUID(source_cursor["executorEpoch"])
        if len(raw.encode()) > 65536:
            raise ValueError("Source record too large")
        self._capacity(len(raw.encode()) * 2 + 8192)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            sequence = self.db.execute("SELECT next_seq FROM streams WHERE device=? AND boot=? AND kind=?", (self.device_id, self.boot_id, kind)).fetchone()[0]
            self.db.execute("INSERT INTO records(device,boot,kind,seq,data) VALUES(?,?,?,?,?)", (self.device_id, self.boot_id, kind, sequence, raw))
            self.db.execute("UPDATE streams SET next_seq=next_seq+1 WHERE device=? AND boot=? AND kind=?", (self.device_id, self.boot_id, kind))
            if source_cursor is not None:
                self.db.execute("INSERT INTO metadata(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", ("source_cursor:" + self.device_id + ":" + self.boot_id, json.dumps(source_cursor)))
            self.db.execute("COMMIT")
            return sequence
        except BaseException:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            raise

    def seal_batch(self, kind, *, max_rows=200, max_payload_bytes=262144, boot_id=None):
        boot = boot_id or self.boot_id
        uuid.UUID(boot)
        if kind not in self.STREAMS or type(max_rows) is not int or not 1 <= max_rows <= 1000 or not 65536 <= max_payload_bytes <= 262144:
            raise ValueError("Invalid batch limit")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            rows = self.db.execute("SELECT seq,data FROM records WHERE device=? AND boot=? AND kind=? AND batch_id IS NULL ORDER BY seq LIMIT ?", (self.device_id, boot, kind, max_rows)).fetchall()
            if not rows:
                self.db.execute("COMMIT")
                return None
            batch_seq = self.db.execute("SELECT next_batch FROM streams WHERE device=? AND boot=? AND kind=?", (self.device_id, boot, kind)).fetchone()[0]
            batch_id, selected = str(uuid.uuid4()), []
            payload = None
            for row in rows:
                if selected and row["seq"] != selected[-1]["sequence"] + 1:
                    break
                candidate = [*selected, {**json.loads(row["data"]), "sequence": row["seq"]}]
                body = {"schema": 1, "agentVersion": "0.1.0", "batchId": batch_id, "deviceId": self.device_id, "bootId": boot, "streamKind": kind,
                        "batchSequence": batch_seq, "firstSequence": candidate[0]["sequence"], "lastSequence": candidate[-1]["sequence"], "rows": candidate}
                encoded = json.dumps(body, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
                if len(encoded) > max_payload_bytes:
                    break
                selected, payload = candidate, encoded
            if not selected:
                raise ValueError("Source record cannot fit an immutable batch")
            digest = hashlib.sha256(payload).hexdigest()
            self._capacity(len(payload) * 2 + 8192)
            self.db.execute("INSERT INTO batches(id,device,boot,kind,batch_seq,first_seq,last_seq,digest,payload) VALUES(?,?,?,?,?,?,?,?,?)", (batch_id, self.device_id, boot, kind, batch_seq, selected[0]["sequence"], selected[-1]["sequence"], digest, payload))
            self.db.execute("UPDATE records SET batch_id=? WHERE device=? AND boot=? AND kind=? AND seq BETWEEN ? AND ?", (batch_id, self.device_id, boot, kind, selected[0]["sequence"], selected[-1]["sequence"]))
            self.db.execute("UPDATE streams SET next_batch=next_batch+1 WHERE device=? AND boot=? AND kind=?", (self.device_id, boot, kind))
            self.db.execute("COMMIT")
            return {"batchId": batch_id, "digest": digest, "payload": payload, "batchSequence": batch_seq, "firstSequence": selected[0]["sequence"], "lastSequence": selected[-1]["sequence"]}
        except BaseException:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            raise

    def seal_retained(self):
        """Recover committed, unsealed records from earlier Agent boots.

        Called before capture workers start. Existing immutable batches and ACKs
        remain unchanged; this is never an SDK-command retry.
        """
        streams = self.db.execute("SELECT DISTINCT boot,kind FROM records WHERE device=? AND batch_id IS NULL", (self.device_id,)).fetchall()
        count = 0
        for stream in streams:
            while self.seal_batch(stream["kind"], boot_id=stream["boot"]) is not None:
                count += 1
        return count

    def pending_batches(self, *, limit=20):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Invalid pending batch limit")
        rows = self.db.execute("SELECT id,digest,payload,batch_seq,first_seq,last_seq FROM batches WHERE acked_at IS NULL AND device=? ORDER BY rowid LIMIT ?", (self.device_id, limit)).fetchall()
        return [{"batchId": row["id"], "digest": row["digest"], "payload": bytes(row["payload"]), "batchSequence": row["batch_seq"], "firstSequence": row["first_seq"], "lastSequence": row["last_seq"]} for row in rows]

    @staticmethod
    def wire_batch(batch):
        return {"batchId": batch["batchId"], "digest": batch["digest"], "payloadBase64url": base64.urlsafe_b64encode(batch["payload"]).decode().rstrip("=")}

    def ack_batch(self, batch_id, digest, *, persisted):
        if persisted is not True:
            return False
        result = self.db.execute("UPDATE batches SET acked_at=COALESCE(acked_at,?) WHERE id=? AND device=? AND digest=?", (time.time_ns() // 1000000, batch_id, self.device_id, digest))
        return result.rowcount == 1

    def retained_batch_count(self):
        return self.db.execute("SELECT count(*) FROM batches WHERE device=?", (self.device_id,)).fetchone()[0]

    def close(self):
        self.db.close()
