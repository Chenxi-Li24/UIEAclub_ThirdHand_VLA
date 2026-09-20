#!/usr/bin/env node
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { loadRuntimeConfig } = require('./service-config');
const { ServiceSupervisor, probeConfiguredService } = require('./service-supervisor');
const { CanInterfaceManager } = require('./can-interface');
const { ensureRuntime } = require('./runtime-ensure');
const { discoverSkills } = require('../../../platform/skill_registry/src/registry');

const ROOT = path.resolve(__dirname, '../../..');

function parseArgs(argv) {
  const command = argv.find(value => !value.startsWith('--'));
  const profileIndex = argv.indexOf('--profile');
  return {
    command,
    json: argv.includes('--json'),
    profile: profileIndex >= 0 ? argv[profileIndex + 1] : (process.env.THIRDHAND_PROFILE || 'default'),
  };
}

function serviceMap(items) {
  return Object.fromEntries(items.map(item => [item.id, item]));
}

function overallFor(command, items, can = null) {
  if (items.length > 0 && items.every(item => item.state === 'stopped')) return 'stopped';
  if (command === 'stop') return 'degraded';
  if (items.length === 0) return 'degraded';
  if (can && can.state !== 'ready') return 'degraded';
  return items.every(item => item.state === 'ready') ? 'ready' : 'degraded';
}

function resourcesForProfile(profile, statuses) {
  const simulatedDevices = {
    simulation: { startouch: 'ready', xvisio: 'ready' },
    'manual-control-simulation': { startouch: 'ready' },
    'gripper-plan-simulation': { startouch: 'ready' },
  };
  return {
    services: Object.fromEntries(statuses.map(item => [item.id, item.state])),
    devices: { ...(simulatedDevices[profile] || {}) },
    models: {},
  };
}

async function lifecycle(command, profile) {
  const profilePath = path.join(ROOT, 'configs', 'runtime', `${profile}.json`);
  if (!fs.existsSync(profilePath)) throw new Error(`unknown runtime profile: ${profile}`);
  const runtimeConfig = loadRuntimeConfig(profilePath, { root: ROOT, nodePath: process.execPath });
  const services = runtimeConfig.services;
  const supervisor = new ServiceSupervisor({ runtimeDir: path.join(ROOT, 'runtime'), services });
  let statuses;
  let can = null;
  let recoveryMode = null;
  if (command === 'start') statuses = await supervisor.startAll();
  else if (command === 'ensure' && runtimeConfig.can?.enabled) {
    const canManager = new CanInterfaceManager({
      interfaceName: runtimeConfig.can.interface,
      bitrate: runtimeConfig.can.bitrate,
      restartMs: runtimeConfig.can.restartMs,
    });
    const ensured = await ensureRuntime({
      canManager,
      serviceSupervisor: supervisor,
      services,
      probeService: probeConfiguredService,
    });
    statuses = ensured.services;
    can = ensured.can;
    recoveryMode = ensured.recoveryMode;
  } else if (command === 'ensure') statuses = await supervisor.ensureAll();
  else if (command === 'stop') statuses = await supervisor.stopAll();
  else statuses = await supervisor.status();

  const resources = resourcesForProfile(profile, statuses);
  const skills = await discoverSkills({ skillsRoot: path.join(ROOT, 'skills'), resources });
  return {
    overall: overallFor(command, statuses, can),
    profile,
    authorizationState: command === 'start' ? 'revoked' : 'revoked',
    can,
    recoveryMode,
    services: serviceMap(statuses),
    skills,
  };
}

function doctor(profile) {
  const profilePath = path.join(ROOT, 'configs', 'runtime', `${profile}.json`);
  const checks = {
    repository: { status: fs.existsSync(path.join(ROOT, '.git')) ? 'ready' : 'unavailable', path: ROOT },
    node: { status: process.versions.node.startsWith('24.') ? 'ready' : 'unavailable', version: process.versions.node },
    profile: { status: fs.existsSync(profilePath) ? 'ready' : 'unavailable', path: profilePath },
    assetManifest: {
      status: fs.existsSync(path.join(ROOT, 'configs/assets/manifest.local.json')) ? 'ready' : 'unavailable',
      reason: 'local_manifest_not_created',
    },
  };
  const required = profile === 'simulation' ? ['repository', 'node', 'profile'] : Object.keys(checks);
  return {
    overall: required.every(id => checks[id].status === 'ready') ? 'ready' : 'degraded',
    profile,
    readOnly: true,
    checks,
    note: 'doctor does not open CAN, cameras, microphones, or model runtimes',
  };
}

function verifyAssets(jsonMode) {
  const manifest = path.join(ROOT, 'configs/assets/manifest.local.json');
  if (!fs.existsSync(manifest)) {
    return { code: 1, report: { ok: false, error: 'local_asset_manifest_missing', manifest } };
  }
  const localPython = path.join(ROOT, 'local/runtimes/python/bin/python');
  const python = fs.existsSync(localPython) ? localPython : 'python3';
  const result = spawnSync(
    python,
    [path.join(ROOT, 'tools/assets/verify_assets.py'), '--project-root', ROOT, '--manifest', manifest, '--json'],
    { cwd: ROOT, encoding: 'utf8' },
  );
  if (result.error) return { code: 1, report: { ok: false, error: result.error.message } };
  try {
    return { code: result.status, report: JSON.parse(result.stdout) };
  } catch {
    return { code: 1, report: { ok: false, error: 'asset_verifier_invalid_output', stderr: result.stderr } };
  }
}

function printHuman(report) {
  console.log(`ThirdHand ${report.profile || ''}: ${report.overall || (report.ok ? 'ready' : 'unavailable')}`.trim());
  if (report.can) {
    const details = [
      report.can.action,
      report.can.interface,
      report.can.bitrate ? `bitrate ${report.can.bitrate}` : null,
      Number.isInteger(report.can.restartMs) ? `restart-ms ${report.can.restartMs}` : null,
      report.recoveryMode ? `mode ${report.recoveryMode}` : null,
    ].filter(Boolean);
    console.log(`  can: ${report.can.state}${details.length ? ` (${details.join(', ')})` : ''}`);
    if (report.can.reason) console.log(`    reason: ${report.can.reason}`);
    if (report.can.detail) console.log(`    detail: ${report.can.detail}`);
  }
  for (const [id, service] of Object.entries(report.services || {})) {
    const details = [
      service.action,
      Number.isInteger(service.port) ? `${service.bind}:${service.port}` : null,
      service.pid ? `pid ${service.pid}` : null,
    ].filter(Boolean);
    console.log(`  ${id}: ${service.state}${details.length ? ` (${details.join(', ')})` : ''}`);
    if (service.reason) console.log(`    reason: ${service.reason}`);
    if (service.logs) {
      console.log(`    stdout: ${service.logs.stdout}`);
      console.log(`    stderr: ${service.logs.stderr}`);
    }
  }
  for (const [id, check] of Object.entries(report.checks || {})) console.log(`  ${id}: ${check.status}`);
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const allowed = new Set(['start', 'ensure', 'stop', 'status', 'doctor', 'verify-assets']);
  if (!allowed.has(args.command)) {
    throw new Error('usage: ./thirdhand start|ensure|stop|status|doctor|verify-assets [--profile NAME] [--json]');
  }

  let report;
  let code = 0;
  if (['start', 'ensure', 'stop', 'status'].includes(args.command)) report = await lifecycle(args.command, args.profile);
  else if (args.command === 'doctor') report = doctor(args.profile);
  else ({ report, code } = verifyAssets(args.json));

  if (args.json) console.log(JSON.stringify(report));
  else printHuman(report);
  if (args.command !== 'verify-assets' && ['degraded', 'unavailable'].includes(report.overall)) code = 1;
  process.exitCode = code;
}

if (require.main === module) {
  main().catch(error => {
    console.error(error.message);
    process.exitCode = 1;
  });
}

module.exports = { resourcesForProfile };
