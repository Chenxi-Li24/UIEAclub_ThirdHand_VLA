'use strict';

const express = require('express');
const fs = require('fs');
const path = require('path');

const POSE_IDS = Object.freeze(['table_center', 'table_left', 'table_right', 'table_front', 'table_back']);
const MAX_FILE_BYTES = 1024 * 1024;

function finiteVector(value, length) {
  return Array.isArray(value) && value.length === length && value.every(Number.isFinite);
}

class ObservationPoseCaptureService {
  constructor({
    output, catalog, getRobotState, simulationOnly = false, speedScale = 0.05, nowMs = Date.now,
  }) {
    this.output = path.resolve(output);
    this.catalog = path.resolve(catalog);
    this.getRobotState = getRobotState;
    this.simulationOnly = simulationOnly === true;
    this.speedScale = Number(speedScale);
    if (!Number.isFinite(this.speedScale) || this.speedScale <= 0 || this.speedScale > 0.05) {
      throw new TypeError('pose validation speed scale must be within (0, 0.05]');
    }
    this.nowMs = nowMs;
    this.lastValidatedPoseId = null;
  }

  _robotState() {
    const robot = this.getRobotState();
    return { ...robot, simulated: this.simulationOnly || robot?.simulated === true };
  }

  _read() {
    if (!fs.existsSync(this.output)) return { schema_version: 1, captures: [] };
    const stat = fs.lstatSync(this.output);
    if (!stat.isFile() || stat.isSymbolicLink() || stat.size > MAX_FILE_BYTES) {
      throw new TypeError('capture manifest is unsafe');
    }
    const value = JSON.parse(fs.readFileSync(this.output, 'utf8'));
    if (!value || value.schema_version !== 1 || !Array.isArray(value.captures)) {
      throw new TypeError('capture manifest is invalid');
    }
    return value;
  }

  _write(value) {
    const encoded = `${JSON.stringify(value, null, 2)}\n`;
    if (Buffer.byteLength(encoded) > MAX_FILE_BYTES) throw new TypeError('capture manifest is oversized');
    fs.mkdirSync(path.dirname(this.output), { recursive: true, mode: 0o700 });
    const temporary = `${this.output}.${process.pid}.${this.nowMs()}.tmp`;
    try {
      fs.writeFileSync(temporary, encoded, { encoding: 'utf8', mode: 0o600, flag: 'wx' });
      fs.renameSync(temporary, this.output);
      fs.chmodSync(this.output, 0o600);
    } finally {
      try { fs.unlinkSync(temporary); } catch (error) { if (error.code !== 'ENOENT') throw error; }
    }
  }

  status() {
    const manifest = this._read();
    const capturedPoseIds = POSE_IDS.filter(poseId =>
      manifest.captures.some(capture => (capture?.name || capture?.pose_id) === poseId));
    return {
      requiredPoseIds: [...POSE_IDS], capturedPoseIds,
      captured: capturedPoseIds.length, remaining: POSE_IDS.length - capturedPoseIds.length,
      catalogPresent: fs.existsSync(this.catalog), catalogValidated: false,
      robot: this._robotState(),
      lastValidatedPoseId: this.lastValidatedPoseId,
      note: '采集只记录当前静止姿态；路径验证需现场逐姿态低速执行后另行签署。',
    };
  }

  capture(command) {
    if (!command || typeof command !== 'object' || Array.isArray(command) ||
        Object.keys(command).length !== 1 || !Object.hasOwn(command, 'pose_id')) {
      return { accepted: false, reason: 'capture_command_invalid' };
    }
    if (!POSE_IDS.includes(command.pose_id)) return { accepted: false, reason: 'pose_id_invalid' };
    const robot = this._robotState();
    if (robot?.simulated === true) return { accepted: false, reason: 'simulated_robot_forbidden' };
    if (robot?.connected !== true) return { accepted: false, reason: 'robot_not_connected' };
    if (robot.stateFresh !== true) return { accepted: false, reason: 'robot_state_stale' };
    if (robot.stationary !== true) return { accepted: false, reason: 'robot_not_stationary' };
    if (!finiteVector(robot.jointsDeg, 6) || !finiteVector(robot.tcpPositionM, 3) ||
        !finiteVector(robot.tcpEulerRad, 3)) {
      return { accepted: false, reason: 'robot_state_invalid' };
    }
    const capture = {
      name: command.pose_id,
      joints_deg: [...robot.jointsDeg],
      tcp_position_m: [...robot.tcpPositionM],
      tcp_euler_rad: [...robot.tcpEulerRad],
      allowed_start_pose_ids: [...new Set([
        command.pose_id,
        ...(this.lastValidatedPoseId === null ? [] : [this.lastValidatedPoseId]),
      ])],
      joint_tolerance_deg: 0.5,
      captured_at: new Date(this.nowMs()).toISOString(),
    };
    const manifest = this._read();
    const captures = manifest.captures.filter(
      item => (item?.name || item?.pose_id) !== command.pose_id
    );
    captures.push(capture);
    this._write({ schema_version: 1, captures });
    const status = this.status();
    return { accepted: true, poseId: command.pose_id, captured: status.captured, remaining: status.remaining };
  }

  validateCurrentPose(command) {
    if (!command || typeof command !== 'object' || Array.isArray(command) ||
        Object.keys(command).sort().join(',') !== 'operator_acknowledged,pose_id') {
      return { accepted: false, reason: 'validation_command_invalid' };
    }
    if (command.operator_acknowledged !== true) {
      return { accepted: false, reason: 'operator_acknowledgement_required' };
    }
    if (!POSE_IDS.includes(command.pose_id)) return { accepted: false, reason: 'pose_id_invalid' };
    const robot = this._robotState();
    if (robot?.simulated === true) return { accepted: false, reason: 'simulated_robot_forbidden' };
    if (robot?.connected !== true) return { accepted: false, reason: 'robot_not_connected' };
    if (robot?.stateFresh !== true) return { accepted: false, reason: 'robot_state_stale' };
    if (robot?.stationary !== true) return { accepted: false, reason: 'robot_not_stationary' };
    if (!finiteVector(robot.jointsDeg, 6)) return { accepted: false, reason: 'robot_state_invalid' };
    const manifest = this._read();
    const index = manifest.captures.findIndex(
      item => (item?.name || item?.pose_id) === command.pose_id
    );
    if (index < 0 || !finiteVector(manifest.captures[index]?.joints_deg, 6)) {
      return { accepted: false, reason: 'pose_not_captured' };
    }
    const maxJointErrorDeg = Math.max(
      ...robot.jointsDeg.map((value, joint) =>
        Math.abs(value - manifest.captures[index].joints_deg[joint]))
    );
    const tolerance = Number(manifest.captures[index].joint_tolerance_deg || 0.5);
    if (!Number.isFinite(maxJointErrorDeg) || maxJointErrorDeg > Math.min(1.0, tolerance)) {
      return { accepted: false, reason: 'pose_joint_error_exceeded' };
    }
    const fromPoseId = this.lastValidatedPoseId;
    const captures = manifest.captures.map((item, captureIndex) =>
      captureIndex === index ? {
        ...item,
        allowed_start_pose_ids: [...new Set([
          command.pose_id,
          ...(Array.isArray(item.allowed_start_pose_ids) ? item.allowed_start_pose_ids : []),
          ...(fromPoseId === null ? [] : [fromPoseId]),
        ])],
        path_validation: {
          tested_at: new Date(this.nowMs()).toISOString(),
          max_joint_error_deg: maxJointErrorDeg,
          speed_scale: this.speedScale,
          operator_acknowledged: true,
        },
      } : item
    );
    this._write({ schema_version: 1, captures });
    this.lastValidatedPoseId = command.pose_id;
    return { accepted: true, poseId: command.pose_id, maxJointErrorDeg };
  }
}

function createObservationPoseCaptureRouter({ service }) {
  const router = express.Router();
  router.use(express.json({ limit: '8kb', strict: true }));
  router.get('/status', (_request, response) => {
    response.setHeader('Cache-Control', 'no-store'); response.json(service.status());
  });
  router.post('/capture', (request, response) => {
    const result = service.capture(request.body);
    response.status(result.accepted ? 200 : 409).json(result);
  });
  router.post('/validate-current', (request, response) => {
    const result = service.validateCurrentPose(request.body);
    response.status(result.accepted ? 200 : 409).json(result);
  });
  return router;
}

module.exports = { ObservationPoseCaptureService, createObservationPoseCaptureRouter, POSE_IDS };
