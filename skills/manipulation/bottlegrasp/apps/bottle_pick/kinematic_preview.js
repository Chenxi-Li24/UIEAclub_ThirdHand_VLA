'use strict';

const { execFile } = require('node:child_process');
const path = require('node:path');
const { deriveExecutionGeometry } = require('../../src/thirdhand_va/action/grasp/execution_plan');

const ROOT = path.resolve(__dirname, '../../../../..');

function unavailable(reason) {
  return { schema: 'thirdhand-kinematic-preview-v1', complete: false,
    reason, frames: [], robotCommandsSent: false };
}

function previewInput(target, config) {
  const source = target?.graspPreview;
  if (!source || !Array.isArray(source.grip_target_xyz_m) ||
      !Array.isArray(source.robot_joints_deg) ||
      !Array.isArray(source.robot_flange_xyz_m)) {
    throw new Error(target?.blockers?.[0] ||
      (target?.basePoseStatus !== 'available' && target?.basePoseStatus) ||
      'base_grasp_or_robot_pose_unavailable');
  }
  const point = source.grip_target_xyz_m;
  const offset = config.grasp.flange_offset_base_m;
  const geometry = deriveExecutionGeometry({
    detectedGraspPointM: point,
    commandedFlangeGraspM: point.map((value, index) => value + offset[index]),
    approachBase: source.approach_base,
  }, config);
  const graspEuler = config.motion.grasp_euler_rad;
  const placeEuler = config.place.euler_rad;
  const stage = (name, positionM, eulerRad, gripperPosition) => ({
    stage: name, positionM, eulerRad, gripperPosition,
  });
  return {
    urdf: path.join(ROOT, 'assets/robot/startouch-v3/FastTouchV3.SLDASM.urdf'),
    startJointsDeg: source.robot_joints_deg,
    startFlangeM: source.robot_flange_xyz_m,
    stages: [
      stage('pregrasp', geometry.pregraspM, graspEuler, 1),
      stage('final_approach', geometry.commandedFlangeGraspM, graspEuler, 1),
      stage('close', geometry.commandedFlangeGraspM, graspEuler, 0),
      stage('lift', geometry.liftM, graspEuler, 0),
      stage('transfer', geometry.prePlaceM, placeEuler, 0),
      stage('lower', geometry.placeM, placeEuler, 0),
      stage('release', geometry.placeM, placeEuler, 1),
      stage('retreat', geometry.retreatM, placeEuler, 1),
    ],
  };
}

async function buildKinematicPreview(target, config, options = {}) {
  let input;
  try { input = previewInput(target, config); }
  catch (error) { return unavailable(error.message); }
  const python = options.python || process.env.THIRDHAND_VA_PREVIEW_PYTHON ||
    path.join(ROOT, 'local/runtimes/vision-python/bin/python');
  return new Promise(resolve => {
    execFile(python, [path.join(__dirname, 'preview_ik.py'), JSON.stringify(input)],
      { timeout: 15000, maxBuffer: 2 * 1024 * 1024 }, (error, stdout) => {
        if (error) return resolve(unavailable('offline_ik_unavailable'));
        try {
          const result = JSON.parse(stdout);
          if (result.schema === 'thirdhand-kinematic-preview-v1' &&
              result.robotCommandsSent === false) return resolve(result);
        } catch { /* Invalid offline solver output is never playable. */ }
        resolve(unavailable('offline_ik_result_invalid'));
      });
  });
}

module.exports = { buildKinematicPreview, previewInput };
