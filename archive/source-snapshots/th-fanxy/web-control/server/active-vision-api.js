'use strict';

const express = require('express');

function createActiveVisionSnapshot({ visionStatus, activeView, graspController, config, nowMs }) {
  const snapshot = visionStatus.snapshot(nowMs());
  const graspExecutionEnabled = config.visionSafety.robotExecutionEnabled === true;
  snapshot.robotExecutionEnabled = graspExecutionEnabled;
  snapshot.targets = snapshot.targets.map(target => {
    const graspReasons = target.graspReasons
      .filter(reason => reason !== 'physical_grasp_execution_locked');
    if (!graspExecutionEnabled) graspReasons.push('physical_grasp_execution_locked');
    return {
      ...target,
      graspAllowed: graspExecutionEnabled &&
        target.d435SameInstanceVerified === true &&
        target.graspGeometryAllowed === true,
      graspReasons: [...new Set(graspReasons)],
    };
  });
  snapshot.activeViewExecutionEnabled = activeView.inFlight !== null;
  snapshot.activeViewExecutionRequested = config.activeView.requested;
  snapshot.activeView.executionEnabled = activeView.inFlight !== null;
  snapshot.activeView.executionRequested = config.activeView.requested;
  snapshot.grasp = graspController.snapshot();
  snapshot.grasp.executionEnabled = graspExecutionEnabled;
  return snapshot;
}

function createActiveVisionRouter(dependencies) {
  const router = express.Router();
  router.get('/status', (_request, response) => {
    response.setHeader('Cache-Control', 'no-store');
    response.json(createActiveVisionSnapshot({ ...dependencies, nowMs: Date.now }));
  });
  return router;
}

module.exports = { createActiveVisionRouter, createActiveVisionSnapshot };
