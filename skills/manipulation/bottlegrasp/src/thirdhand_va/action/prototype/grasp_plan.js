'use strict';

const { gripTargetToFlangePose } = require('../grasp/grip_transform');
const builtPlans = new WeakSet();

function deepFreeze(value) {
  if (value && typeof value === 'object') {
    Object.values(value).forEach(deepFreeze);
    Object.freeze(value);
  }
  return value;
}

function vector3(value) {
  return Array.isArray(value) && value.length === 3 &&
    Array.from(value).every(Number.isFinite);
}

function positive(value) { return Number.isFinite(value) && value > 0; }
function rounded(value) { return Number(value.toFixed(12)); }

function buildPrototypeGraspPlan(input = {}) {
  if (typeof input.requestId !== 'string' || !input.requestId.trim()) {
    throw new TypeError('prototype_request_id_invalid');
  }
  if (!vector3(input.target?.positionM) || !vector3(input.target?.eulerRad)) {
    throw new TypeError('prototype_target_invalid');
  }
  if (!positive(input.widthM)) throw new TypeError('prototype_width_invalid');
  if (![input.pregraspOffsetM,input.liftDistanceM,input.linearSpeedMps].every(positive)) {
    throw new TypeError('prototype_motion_invalid');
  }
  const matrix = input.flangeToGrip;
  if (!Array.isArray(matrix) || matrix.length !== 4 || !Array.from(matrix).every(row =>
    Array.isArray(row) && row.length === 4 && Array.from(row).every(Number.isFinite))) {
    throw new TypeError('prototype_grip_transform_invalid');
  }
  const flange = gripTargetToFlangePose(input.target, matrix);
  const approach = flange.positionM;
  const pregrasp = approach.map((value,index) => rounded(value + (index === 2 ? input.pregraspOffsetM : 0)));
  const lift = approach.map((value,index) => rounded(value + (index === 2 ? input.liftDistanceM : 0)));
  const approachTime = input.pregraspOffsetM / input.linearSpeedMps;
  const liftTime = input.liftDistanceM / input.linearSpeedMps;
  if (![...pregrasp,...approach,...lift,...flange.eulerRad,approachTime,liftTime].every(Number.isFinite)) {
    throw new TypeError('prototype_motion_invalid');
  }
  const move = (position,time) => ({cmd:'move_l',position:[...position],
    euler:[...flange.eulerRad],time_sec:time});
  // No starting pose is supplied: this duration is a nominal preview value,
  // not a trajectory duration from an actual robot configuration.
  const plan = deepFreeze({schema:'thirdhand-prototype-grasp-plan-v1',requestId:input.requestId,
    simulationOnly:true,widthM:input.widthM,steps:[
      {phase:'pregrasp',command:move(pregrasp,approachTime)},
      {phase:'approach',command:move(approach,approachTime)},
      {phase:'grip',command:{cmd:'gripper',position:0}},
      {phase:'lift',command:move(lift,liftTime)},
    ]});
  builtPlans.add(plan);
  return plan;
}

function isPrototypePlan(value) { return builtPlans.has(value); }
module.exports = { buildPrototypeGraspPlan, isPrototypePlan };
