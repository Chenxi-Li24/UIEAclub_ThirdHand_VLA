'use strict';

const fs = require('node:fs');
const { buildPrototypeGraspPlan } = require('../../src/thirdhand_va/action/prototype/grasp_plan');
const { PrototypeSimulator } = require('../../src/thirdhand_va/action/prototype/simulator');
const { PrototypeGraspExecutor } = require('../../src/thirdhand_va/action/prototype/executor');

function run(args) {
  const forbidden = new Set(['--execute','--real','--backend','--can','--socket']);
  if (args.some(arg => forbidden.has(arg.split('=')[0]))) {
    throw new Error('prototype_hardware_option_forbidden');
  }
  if (args.length !== 2 || args[0] !== '--fixture' || !args[1] || args[1].startsWith('--')) {
    throw new Error('prototype_arguments_invalid');
  }
  let plan;
  try {
    plan = buildPrototypeGraspPlan(JSON.parse(fs.readFileSync(args[1],'utf8')));
  } catch {
    throw new Error('prototype_fixture_invalid');
  }
  const simulator = new PrototypeSimulator();
  const executor = new PrototypeGraspExecutor({simulator});
  executor.start(plan);
  for (let index = 0; index < plan.steps.length && executor.snapshot().status === 'running'; index += 1) {
    executor.ack({type:'command_complete',request_id:executor.snapshot().inFlightRequestId,reached:true});
  }
  const finalState = executor.snapshot();
  if (finalState.status !== 'complete') throw new Error('prototype_execution_failed');
  return {schema:'thirdhand-prototype-grasp-report-v1',simulationOnly:true,
    status:finalState.status,plan,commands:simulator.commands,finalState};
}

try {
  process.stdout.write(`${JSON.stringify(run(process.argv.slice(2)),null,2)}\n`);
} catch (error) {
  process.stderr.write(`${JSON.stringify({error:error.message})}\n`);
  process.exitCode = 2;
}
