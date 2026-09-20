'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const ROOT = path.resolve(__dirname, '..', '..', '..');

test('agent.trace is forwarded to the communication log callback only', () => {
  const voiceControl = fs.readFileSync(
    path.join(ROOT, 'apps/web/public/js/voice-control.js'),
    'utf8',
  );
  const main = fs.readFileSync(
    path.join(ROOT, 'apps/web/public/js/main.js'),
    'utf8',
  );

  assert.match(voiceControl, /this\.onAgentTrace\s*=\s*options\.onAgentTrace/);
  const traceCase = voiceControl.match(
    /case 'agent\.trace':[\s\S]*?(?=\n\s*case |\n\s*default:)/,
  );
  assert.ok(traceCase, 'VoiceControl must handle agent.trace');
  assert.match(traceCase[0], /this\.onAgentTrace\?\.\(message\.payload\s*\|\|\s*\{\}\)/);
  assert.doesNotMatch(traceCase[0], /_renderAssistantResponse/);

  assert.match(main, /function formatAgentTrace\(payload\)/);
  assert.match(main, /onAgentTrace:\s*payload\s*=>\s*ui\?\._log\(formatAgentTrace\(payload\)\)/);
});
