'use strict';

const assert = require('node:assert/strict');

const { WorkflowClient } = require(
  '../../../src/thirdhand_va/action/grasp/workflow'
);

assert.throws(() => new WorkflowClient({}), /cameraBridge/);
console.log('PASS workflow requires explicit local V+A adapters');
