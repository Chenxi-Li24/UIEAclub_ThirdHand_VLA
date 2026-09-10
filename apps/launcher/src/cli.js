#!/usr/bin/env node
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { loadServiceConfig } = require('./service-config');
const { ServiceSupervisor } = require('./service-supervisor');
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

function overallFor(command, items) {
  if (command === 'stop') return items.every(item => item.state === 'stopped') ? 'stopped' : 'degraded';
  if (items.length === 0) return 'degraded';
  return items.every(item => item.state === 'ready') ? 'ready' : 'degraded';
}

async function lifecycle(command, profile) {
  const profilePath = path.join(ROOT, 'configs', 'runtime', `${profile}.json`);
  if (!fs.existsSync(profilePath)) throw new Error(`unknown runtime profile: ${profile}`);
  const services = loadServiceConfig(profilePath, { root: ROOT, nodePath: process.execPath });
  const supervisor = new ServiceSupervisor({ runtimeDir: path.join(ROOT, 'runtime'), services });
  let statuses;
  if (command === 'start') statuses = await supervisor.startAll();
  else if (command === 'stop') statuses = await supervisor.stopAll();
  else statuses = await supervisor.status();

  const resources = {
    services: Object.fromEntries(statuses.map(item => [item.id, item.state])),
    devices: profile === 'simulation' ? { startouch: 'ready', xvisio: 'ready' } : {},
    models: {},
  };
  const skills = await discoverSkills({ skillsRoot: path.join(ROOT, 'skills'), resources });
  return {
    overall: overallFor(command, statuses),
    profile,
    authorizationState: command === 'start' ? 'revoked' : 'revoked',
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
  for (const [id, service] of Object.entries(report.services || {})) {
    console.log(`  ${id}: ${service.state}${service.pid ? ` (pid ${service.pid})` : ''}`);
  }
  for (const [id, check] of Object.entries(report.checks || {})) console.log(`  ${id}: ${check.status}`);
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const allowed = new Set(['start', 'stop', 'status', 'doctor', 'verify-assets']);
  if (!allowed.has(args.command)) {
    throw new Error('usage: ./thirdhand start|stop|status|doctor|verify-assets [--profile NAME] [--json]');
  }

  let report;
  let code = 0;
  if (['start', 'stop', 'status'].includes(args.command)) report = await lifecycle(args.command, args.profile);
  else if (args.command === 'doctor') report = doctor(args.profile);
  else ({ report, code } = verifyAssets(args.json));

  if (args.json) console.log(JSON.stringify(report));
  else printHuman(report);
  if (args.command !== 'verify-assets' && ['degraded', 'unavailable'].includes(report.overall)) code = 1;
  process.exitCode = code;
}

main().catch(error => {
  console.error(error.message);
  process.exitCode = 1;
});
