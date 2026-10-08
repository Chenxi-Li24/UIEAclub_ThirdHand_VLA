'use strict';

const fs = require('node:fs');
const path = require('node:path');

const POINTS_FILE = path.resolve(__dirname, '../../../skills/manipulation/meituan_battery_pnp/points.md');

function loadMeituanPoints(file = POINTS_FILE) {
  const lines = fs.readFileSync(file, 'utf8').split(/\r?\n/);
  const points = [];
  const names = new Set();
  let inTable = false;
  for (const line of lines) {
    const cells = line.trim().split('|').slice(1, -1).map(cell => cell.trim());
    if (!inTable) {
      if (cells.slice(0, 7).join(',') === 'Point,J1,J2,J3,J4,J5,J6') inTable = true;
      continue;
    }
    if (!line.trim().startsWith('|')) break;
    if (cells.every(cell => /^:?-+:?$/.test(cell))) continue;
    const name = cells[0];
    const values = cells.slice(1, 7);
    if (!/^[A-Za-z][A-Za-z0-9_]*$/.test(name || '') || names.has(name) ||
        values.length !== 6 || values.some(value => !/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/.test(value))) {
      throw new Error('Invalid or duplicate waypoint');
    }
    const jointsDeg = values.map(Number);
    if (!jointsDeg.every(Number.isFinite)) throw new Error('Invalid joint angle');
    names.add(name);
    points.push({ name, jointsDeg });
  }
  if (!points.length) throw new Error('Waypoint table is missing or empty');
  return points;
}

function loadMeituanGripperOpenings(file = POINTS_FILE) {
  const lines = fs.readFileSync(file, 'utf8').split(/\r?\n/);
  const cellsOf = line => line.trim().split('|').slice(1, -1).map(cell => cell.trim());
  const start = lines.findIndex(line => cellsOf(line).slice(0, 2).join(',') === 'Action,Target opening');
  if (start < 0) throw new Error('Gripper openings table is missing');
  const openings = {};
  for (const line of lines.slice(start + 1)) {
    if (!line.trim().startsWith('|')) break;
    const cells = cellsOf(line);
    if (cells.every(cell => /^:?-+:?$/.test(cell))) continue;
    const key = cells[0] === 'Grasp' ? 'graspPercent' : cells[0] === 'Release' ? 'releasePercent' : null;
    const match = /^(\d+(?:\.\d+)?)%$/.exec(cells[1] || '');
    if (!key || !match || Object.hasOwn(openings, key)) throw new Error('Invalid or duplicate gripper opening');
    const value = Number(match[1]);
    if (!Number.isFinite(value) || value < 0 || value > 100) throw new Error('Gripper opening out of range');
    openings[key] = value;
  }
  if (!Object.hasOwn(openings, 'graspPercent') || !Object.hasOwn(openings, 'releasePercent')) {
    throw new Error('Gripper openings are incomplete');
  }
  return openings;
}

function recordMeituanPoint(file = POINTS_FILE, name, jointsDeg) {
  if (typeof name !== 'string' || !/^[A-Z][A-Z0-9_]{0,63}$/.test(name)) {
    const error = new Error('Point name must be uppercase letters, digits or underscores');
    error.code = 'point_name_invalid';
    throw error;
  }
  if (!Array.isArray(jointsDeg) || jointsDeg.length !== 6 ||
      !jointsDeg.every(Number.isFinite)) {
    const error = new Error('Fresh six-axis feedback is required');
    error.code = 'robot_state_unavailable';
    throw error;
  }
  loadMeituanPoints(file);
  const markdown = fs.readFileSync(file, 'utf8');
  const eol = markdown.includes('\r\n') ? '\r\n' : '\n';
  const lines = markdown.split(/\r?\n/);
  const header = lines.findIndex(line =>
    line.trim().split('|').slice(1, 8).map(cell => cell.trim()).join(',') ===
    'Point,J1,J2,J3,J4,J5,J6');
  if (header < 0) throw new Error('Waypoint table is missing');
  let end = header + 1;
  while (end < lines.length && lines[end].trim().startsWith('|')) end++;
  const saved = jointsDeg.map(value => Number(value.toFixed(3)));
  const rowIndex = lines.findIndex((line, index) => index > header && index < end &&
    line.trim().split('|')[1]?.trim() === name);
  lines.splice(rowIndex < 0 ? end : rowIndex, rowIndex < 0 ? 0 : 1,
    `| ${name} | ${saved.map(value => value.toFixed(3)).join(' | ')} | Recorded from 1034 live joint feedback |`);
  const temporary = file + '.' + process.pid + '.' + require('node:crypto').randomUUID() + '.tmp';
  try {
    fs.writeFileSync(temporary, lines.join(eol), {
      flag: 'wx', mode: fs.statSync(file).mode,
    });
    fs.renameSync(temporary, file);
  } finally {
    if (fs.existsSync(temporary)) fs.unlinkSync(temporary);
  }
  return { name, jointsDeg: saved, updated: rowIndex >= 0 };
}

module.exports = { loadMeituanPoints, loadMeituanGripperOpenings, recordMeituanPoint, POINTS_FILE };
