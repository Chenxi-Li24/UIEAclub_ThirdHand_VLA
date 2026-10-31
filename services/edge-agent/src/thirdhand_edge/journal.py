"""Durable at-most-once submission record. Unknown never means safe to retry."""
import json
import sqlite3


class JournalConflict(ValueError):
    pass


class CommandJournal:
    def __init__(self, path):
        self.db = sqlite3.connect(path, timeout=2, isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS commands(
            id TEXT PRIMARY KEY, digest TEXT NOT NULL, result TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS sequences(
            context TEXT PRIMARY KEY, maximum INTEGER NOT NULL);
        """)
        self.stop_db = sqlite3.connect(path, timeout=0, isolation_level=None)
        self.stop_db.execute("PRAGMA synchronous=FULL")

    def lookup(self, command_id):
        row = self.db.execute("SELECT result FROM commands WHERE id=?", (command_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def reserve(self, payload, digest):
        command_id = payload["commandId"]
        db = self.stop_db if payload["purpose"] == "stop" else self.db
        try:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT digest,result FROM commands WHERE id=?", (command_id,)).fetchone()
            if previous:
                if previous[0] != digest:
                    raise JournalConflict("COMMAND_ID_CONFLICT")
                db.execute("COMMIT")
                return False, json.loads(previous[1])
            if payload["purpose"] == "command":
                context = json.dumps([payload[name] for name in ("deviceId", "bootId", "executorEpoch", "connectionId", "leaseId", "leaseEpoch")], separators=(",", ":"))
                old = db.execute("SELECT maximum FROM sequences WHERE context=?", (context,)).fetchone()
                if old and payload["sequence"] <= old[0]:
                    raise JournalConflict("SEQUENCE_REPLAYED")
                db.execute("INSERT INTO sequences(context,maximum) VALUES(?,?) ON CONFLICT(context) DO UPDATE SET maximum=excluded.maximum", (context, payload["sequence"]))
            result = {"commandId": command_id, "state": "unknown", "code": "SUBMISSION_RESULT_UNKNOWN"}
            db.execute("INSERT INTO commands(id,digest,result) VALUES(?,?,?)", (command_id, digest, json.dumps(result)))
            db.execute("COMMIT")
            return True, result
        except BaseException:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise

    def finish(self, command_id, result, *, priority=False):
        db = self.stop_db if priority else self.db
        db.execute("UPDATE commands SET result=? WHERE id=?", (json.dumps(result, allow_nan=False), command_id))

    def close(self):
        self.stop_db.close()
        self.db.close()
