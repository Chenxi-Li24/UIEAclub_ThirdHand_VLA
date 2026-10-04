'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { buildPrototypeGraspPlan } = require('../../../src/thirdhand_va/action/prototype/grasp_plan');
const { PrototypeSimulator } = require('../../../src/thirdhand_va/action/prototype/simulator');
const { PrototypeGraspExecutor } = require('../../../src/thirdhand_va/action/prototype/executor');

function plan() {
  return buildPrototypeGraspPlan({requestId:'trial',target:{positionM:[0.3,0,0.1],eulerRad:[0,0,0]},
    widthM:0.04,flangeToGrip:[[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]],
    pregraspOffsetM:0.1,liftDistanceM:0.05,linearSpeedMps:0.02});
}
const complete = phase => ({type:'command_complete',request_id:`trial:${phase}`,reached:true});

test('correlated acknowledgements complete exactly four simulated phases', () => {
  const simulator = new PrototypeSimulator();
  const executor = new PrototypeGraspExecutor({simulator});
  assert.equal(executor.start(plan()).accepted,true);
  assert.equal(simulator.commands.length,1);
  assert.equal(executor.start(plan()).reason,'prototype_session_active');
  assert.equal(executor.ack({...complete('pregrasp'),request_id:'other'}).handled,false);
  assert.equal(executor.ack({...complete('pregrasp'),type:'status'}).handled,false);
  executor.ack(complete('pregrasp'));
  assert.equal(simulator.commands.length,2);
  assert.equal(executor.ack(complete('pregrasp')).duplicate,true);
  assert.equal(simulator.commands.length,2);
  for (const phase of ['approach','grip','lift']) executor.ack(complete(phase));
  assert.equal(executor.snapshot().status,'complete');
  assert.deepEqual(simulator.commands.map(command => command.request_id),
    ['trial:pregrasp','trial:approach','trial:grip','trial:lift']);
  assert.ok(simulator.commands.every(command => command.source === 'prototype_grasp_validation'));
  assert.ok(Object.isFrozen(simulator.commands[0].position));
});

test('failed completion or failed send emits no later phases', () => {
  for (const failure of ['send','throw','completion']) {
    const simulator = new PrototypeSimulator();
    const originalSend = simulator.send.bind(simulator);
    simulator.send = command => {
      if (command.request_id === 'trial:approach' && failure === 'send') return false;
      if (command.request_id === 'trial:approach' && failure === 'throw') throw new Error('sim failure');
      return originalSend(command);
    };
    const executor = new PrototypeGraspExecutor({simulator});
    assert.equal(executor.ack(complete('pregrasp')).handled,false);
    executor.start(plan());
    executor.ack({...complete('pregrasp'),reached:failure !== 'completion'});
    assert.equal(executor.snapshot().status,'failed');
    executor.ack(complete('pregrasp'));
    assert.equal(simulator.commands.length,1);
  }
});

test('simulator keeps independent immutable command copies', () => {
  const simulator = new PrototypeSimulator();
  const command = {position:[1,2,3]};
  simulator.send(command); command.position[0] = 9;
  assert.deepEqual(simulator.commands[0].position,[1,2,3]);
  assert.throws(() => simulator.commands.push({}), TypeError);
});

test('executor rejects arbitrary adapters and malformed plans before sending', () => {
  assert.throws(() => new PrototypeGraspExecutor({simulator:{send(){return true;}}}),
    /prototype_simulator_required/);
  const simulator = new PrototypeSimulator();
  const executor = new PrototypeGraspExecutor({simulator});
  for (const value of [null,{}, {...plan(),simulationOnly:false}]) {
    assert.throws(() => executor.start(value), /prototype_plan_invalid/);
  }
  assert.equal(simulator.commands.length,0);
});

test('completed executor cannot reuse request IDs to consume old acknowledgements', () => {
  const executor = new PrototypeGraspExecutor({simulator:new PrototypeSimulator()});
  executor.start(plan());
  for (const phase of ['pregrasp','approach','grip','lift']) executor.ack(complete(phase));
  assert.equal(executor.start(plan()).accepted,false);
});
