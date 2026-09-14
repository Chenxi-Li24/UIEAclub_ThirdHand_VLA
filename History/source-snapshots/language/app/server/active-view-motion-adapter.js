'use strict';

function finiteVector(value) {
  return Array.isArray(value) && value.length === 3 && value.every(Number.isFinite);
}

function materializeRefinement({
  tcpPositionM,
  tcpEulerRad,
  deltaBaseM,
  rotationDeltaBaseRad,
  maxTranslationM,
  maxRotationRad,
}) {
  if (![tcpPositionM, tcpEulerRad, deltaBaseM, rotationDeltaBaseRad].every(finiteVector)) {
    return null;
  }
  if (![maxTranslationM, maxRotationRad].every(
    value => Number.isFinite(value) && value > 0
  )) return null;
  const distanceM = Math.hypot(...deltaBaseM);
  const rotationRad = Math.hypot(...rotationDeltaBaseRad);
  if ((distanceM <= 1e-12 && rotationRad <= 1e-12) ||
      distanceM > maxTranslationM + 1e-12 ||
      rotationRad > maxRotationRad + 1e-12) return null;
  const position = tcpPositionM.map((value, index) => value + deltaBaseM[index]);
  if (!position.every(Number.isFinite)) return null;
  return {
    position,
    euler: [...tcpEulerRad],
    rotationDeltaBaseRad: [...rotationDeltaBaseRad],
    timeSec: Math.max(2.0, distanceM / 0.01),
  };
}

module.exports = { materializeRefinement };
