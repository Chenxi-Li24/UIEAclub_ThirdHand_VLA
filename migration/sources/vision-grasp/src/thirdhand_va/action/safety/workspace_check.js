'use strict';

const DEFAULT_WORKSPACE = Object.freeze({
  x: Object.freeze([0.15, 0.66]),
  y: Object.freeze([-0.45, 0.45]),
  z: Object.freeze([0.04, 0.65]),
});

function isRange(value) {
  return Array.isArray(value) && value.length === 2 &&
    value.every(Number.isFinite) && value[0] <= value[1];
}

function checkWorkspace(pointM, bounds = DEFAULT_WORKSPACE, prefix = 'workspace') {
  if (typeof prefix !== 'string' || !/^[a-z][a-z_]*$/.test(prefix)) {
    return { allowed: false, blockers: ['workspace_prefix_invalid'] };
  }
  if (!Array.isArray(pointM) || pointM.length !== 3 ||
      !pointM.every(Number.isFinite)) {
    return { allowed: false, blockers: [`${prefix}_point_invalid`] };
  }
  if (!bounds || !isRange(bounds.x) || !isRange(bounds.y) || !isRange(bounds.z)) {
    return { allowed: false, blockers: [`${prefix}_config_invalid`] };
  }
  const blockers = [];
  for (const [index, axis] of ['x', 'y', 'z'].entries()) {
    if (pointM[index] < bounds[axis][0] || pointM[index] > bounds[axis][1]) {
      blockers.push(`${prefix}_${axis}_out_of_bounds`);
    }
  }
  return { allowed: blockers.length === 0, blockers };
}

module.exports = { DEFAULT_WORKSPACE, checkWorkspace };
