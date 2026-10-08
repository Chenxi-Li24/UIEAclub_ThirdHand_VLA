'use strict';

const { randomUUID } = require('node:crypto');
const { createInterface } = require('node:readline/promises');

const BASE_URL = 'http://127.0.0.1:8766';

function validPoint(point) {
  return Array.isArray(point) && point.length === 3 && point.every(Number.isFinite);
}

function validPreview(preview, targetId, now) {
  return preview?.targetId === targetId && preview.executable === true &&
    Array.isArray(preview.blockers) && preview.blockers.length === 0 &&
    typeof preview.previewId === 'string' && preview.previewId.length > 0 &&
    Number.isFinite(preview.expiresAtMs) && preview.expiresAtMs - now >= 50 &&
    typeof preview.plan?.requestId === 'string' && preview.plan.requestId.length > 0 &&
    validPoint(preview.coordinates?.camera_xyz_m) &&
    validPoint(preview.coordinates?.surface_xyz_m) &&
    validPoint(preview.coordinates?.grip_target_xyz_m) &&
    typeof preview.evidence?.calibrationId === 'string';
}

function matchesDisplayedTarget(displayed, refreshed) {
  if (displayed.evidence.calibrationId !== refreshed.evidence.calibrationId) return false;
  return Object.keys(displayed.coordinates).every(key =>
    displayed.coordinates[key].every((value, axis) =>
      Math.abs(value - refreshed.coordinates[key][axis]) <= 0.005
    )
  );
}

async function prompt(message) {
  const input = createInterface({ input: process.stdin, output: process.stdout });
  try {
    return await input.question(`${message}\n> `);
  } finally {
    input.close();
  }
}

async function main(argv = process.argv.slice(2), dependencies = {}) {
  const write = dependencies.write || (line => console.log(line));
  const writeError = dependencies.writeError || (line => console.error(line));
  const fetchImpl = dependencies.fetchImpl || globalThis.fetch;
  const ask = dependencies.ask || prompt;
  const wait = dependencies.wait || (milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds)));
  const now = dependencies.now || Date.now;
  const id = dependencies.id || randomUUID;
  const execute = argv.includes('--execute');
  const targetIndex = argv.indexOf('--target-id');
  if (targetIndex < 0 || !/^[1-5]$/.test(argv[targetIndex + 1] || '') ||
      argv.length !== (execute ? 3 : 2) ||
      argv.some((value, index) => index !== targetIndex &&
        index !== targetIndex + 1 && value !== '--execute')) {
    writeError('usage: node scripts/action/grip_live_demo.js --target-id 1..5 [--execute]');
    return 2;
  }
  const targetId = Number(argv[targetIndex + 1]);
  const baseUrl = dependencies.baseUrl || BASE_URL;
  const get = async path => {
    const response = await fetchImpl(`${baseUrl}${path}`, { method: 'GET', signal: AbortSignal.timeout(4000) });
    const body = await response.json();
    if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`);
    return body;
  };
  const post = async (path, body) => {
    const response = await fetchImpl(`${baseUrl}${path}`, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body), signal: AbortSignal.timeout(4000),
    });
    const result = await response.json();
    if (!response.ok || result.accepted !== true) {
      throw new Error(`${path}: ${result.reason || `HTTP ${response.status}`}`);
    }
    return result;
  };
  let startSent = false;
  let completed = false;
  let requestId = null;
  let interrupted = false;
  let wakeInterruption;
  const interruption = new Promise(resolve => { wakeInterruption = resolve; });
  const onSignal = () => { interrupted = true; wakeInterruption(null); };
  const confirm = message => Promise.race([ask(message), interruption]);
  try {
    const health = await get('/health');
    const status = await get('/api/va/test/status');
    const displayed = await get(`/api/va/test/preview?target_id=${targetId}`);
    write(JSON.stringify({ targetId, coordinates: displayed.coordinates,
      blockers: displayed.blockers, executable: displayed.executable,
      health: { camera_ready: health.camera_ready,
        robot_control_enabled: health.robot_control_enabled, home: health.home },
      session: status, controlPage: 'http://192.168.58.68:9983/' }, null, 2));
    if (status.active || !health.camera_ready || !health.robot_control_enabled ||
        health.home?.ready !== true || !validPreview(displayed, targetId, now())) {
      writeError('not executable: resolve preview blockers and physical validation first');
      return 2;
    }
    if (!execute) {
      write('read-only preview; pass --execute to request supervised motion');
      return 0;
    }
    process.once('SIGINT', onSignal);
    process.once('SIGTERM', onSignal);
    const approval = await confirm(`Confirm clear workspace and physical E-stop. Type START ${targetId} to proceed`);
    if (interrupted || approval !== `START ${targetId}`) return 2;
    const refreshed = await get(`/api/va/test/preview?target_id=${targetId}`);
    if (!validPreview(refreshed, targetId, now()) ||
        !matchesDisplayedTarget(displayed, refreshed)) {
      writeError('target or calibration changed; preview again before moving');
      return 2;
    }
    requestId = refreshed.plan.requestId;
    startSent = true;
    await post('/api/va/test/start', { previewId: refreshed.previewId, requestId });
    const deadline = now() + 240000;
    while (!interrupted && now() < deadline) {
      const current = await get('/api/va/test/status');
      if (current.phase === 'complete' && current.active === false) {
        completed = true;
        write('supervised grasp sequence complete; inspect physical result');
        return 0;
      }
      if (current.phase === 'stopped' || current.phase === 'uncertain_stop' ||
          current.active !== true) throw new Error(`session ended: ${current.phase}`);
      if (current.phase === 'awaiting_confirmation' &&
          current.awaiting_confirmation === true &&
          typeof current.commandPhase === 'string' && current.commandPhase) {
        const phase = current.commandPhase;
        const answer = await confirm(`Review phase ${phase}. Type NEXT ${phase} or STOP`);
        if (interrupted || answer !== `NEXT ${phase}`) throw new Error('operator stopped');
        const checked = await get('/api/va/test/status');
        if (checked.active !== true || checked.phase !== 'awaiting_confirmation' ||
            checked.commandPhase !== phase || checked.requestId !== requestId) {
          throw new Error('supervised phase changed');
        }
        await post('/api/va/test/next', {
          confirmationId: id(), expectedPhase: phase, requestId,
        });
      } else {
        await wait(200);
      }
    }
    throw new Error(interrupted ? 'signal received' : 'supervised session timed out');
  } catch (error) {
    writeError(`grip demo aborted: ${error.message || error}`);
    return 3;
  } finally {
    process.removeListener('SIGINT', onSignal);
    process.removeListener('SIGTERM', onSignal);
    if (startSent && !completed) {
      try {
        await post('/api/va/test/stop', { requestId });
        writeError('supervised stop requested; verify the robot is stationary');
      } catch (error) {
        writeError(`stop unconfirmed: ${error.message || error}; use the physical E-stop if needed`);
      }
    }
  }
}

if (require.main === module) {
  main().then(code => { process.exitCode = code; });
}

module.exports = { main };
