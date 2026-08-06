'use strict';

const fs = require('fs');
const path = require('path');
const { canonicalJson } = require('./active-view-authorization');

const MAX_AUDIT_LINE_BYTES = 64 * 1024;

class ActiveViewAuditLog {
  constructor(filePath, { nowMs = Date.now } = {}) {
    if (typeof filePath !== 'string' || filePath.length === 0) {
      throw new TypeError('audit path is required');
    }
    this.path = path.resolve(filePath);
    this.nowMs = nowMs;
    fs.mkdirSync(path.dirname(this.path), { recursive: true, mode: 0o700 });
    this.nextSequence = this._readNextSequence();
    if (!fs.existsSync(this.path)) fs.closeSync(fs.openSync(this.path, 'a', 0o600));
    fs.chmodSync(this.path, 0o600);
  }

  _readNextSequence() {
    if (!fs.existsSync(this.path)) return 1;
    const stat = fs.lstatSync(this.path);
    if (stat.isSymbolicLink() || !stat.isFile()) throw new TypeError('audit path must be a regular file');
    const text = fs.readFileSync(this.path, 'utf8');
    if (!text) return 1;
    const lines = text.endsWith('\n') ? text.slice(0, -1).split('\n') : text.split('\n');
    let previous = 0;
    for (const line of lines) {
      if (Buffer.byteLength(`${line}\n`) > MAX_AUDIT_LINE_BYTES) {
        throw new TypeError('existing audit record exceeds 64 KiB');
      }
      let record;
      try { record = JSON.parse(line); } catch { throw new TypeError('existing audit log is invalid JSON'); }
      canonicalJson(record);
      if (!Number.isSafeInteger(record.sequence) || record.sequence !== previous + 1) {
        throw new TypeError('existing audit sequence is invalid');
      }
      previous = record.sequence;
    }
    return previous + 1;
  }

  append(event) {
    if (!event || typeof event !== 'object' || Array.isArray(event)) {
      throw new TypeError('audit event must be an object');
    }
    const record = {
      ...event,
      sequence: this.nextSequence,
      writtenAtMs: this.nowMs(),
    };
    let line;
    try { line = `${canonicalJson(record)}\n`; } catch { throw new TypeError('audit record must be finite JSON'); }
    if (Buffer.byteLength(line) > MAX_AUDIT_LINE_BYTES) {
      throw new TypeError('audit record exceeds 64 KiB');
    }
    fs.appendFileSync(this.path, line, { encoding: 'utf8', mode: 0o600, flag: 'a' });
    fs.chmodSync(this.path, 0o600);
    this.nextSequence += 1;
    return record;
  }
}

module.exports = { ActiveViewAuditLog, MAX_AUDIT_LINE_BYTES };
