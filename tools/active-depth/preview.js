'use strict';

const fs = require('node:fs');
const { buildActiveDepthPreview } = require('../../apps/web/src/active-depth/preview');

function main(args) {
  if (args.length !== 4 || args[0] !== '--fixture' || args[2] !== '--target-id'
      || !/^[1-5]$/.test(args[3])) {
    process.stderr.write('unsupported arguments; use --fixture FILE --target-id 1..5 (never --execute)\n');
    return 2;
  }
  try {
    const fixture = JSON.parse(fs.readFileSync(args[1], 'utf8'));
    if (Number(fixture.observation?.selectedStableId) !== Number(args[3])) {
      process.stderr.write('target ID does not match selected stable ID\n');
      return 2;
    }
    const preview = buildActiveDepthPreview(fixture);
    process.stdout.write(`${JSON.stringify(preview, null, 2)}\n`);
    return preview.blockers.length ? 2 : 0;
  } catch (error) {
    process.stderr.write(`${error.message}\n`);
    return 2;
  }
}

process.exitCode = main(process.argv.slice(2));
