'use strict';

const fs = require('fs');
const path = require('path');

class StatusStore {
  constructor(filePath) {
    this.filePath = filePath;
    this.latest = null;
  }

  write(status) {
    this.latest = Object.freeze({ ...status, updatedAt: new Date().toISOString() });
    fs.mkdirSync(path.dirname(this.filePath), { recursive: true });
    const tmp = `${this.filePath}.tmp`;
    fs.writeFileSync(tmp, `${JSON.stringify(this.latest, null, 2)}\n`);
    fs.renameSync(tmp, this.filePath);
  }

  read() {
    return this.latest;
  }
}

module.exports = { StatusStore };
