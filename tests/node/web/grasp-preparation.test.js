'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const geometry=require('../../../apps/web/src/grasp/geometry');
geometry.buildPreparation=require('../../../apps/web/src/grasp/preparation').buildPreparation;
const {fixture}=require('./grasp-geometry.test');
test('preparation raises without tilting, then levels at safe SDK height preserving yaw',()=>{
 const f=fixture();Object.assign(f.config,{orientationMode:'horizontal',autoLevelBeforeDepth:true,safeLevelSdkZM:.3064});
 f.robot.flange_euler_rad=[.1,.49,.2];
 const p=geometry.buildPreparation(f.robot,f.config);
 assert.deepEqual(p.map(x=>x.phase),['preparing_raise','preparing_level']);
 assert.ok(p[0].path.every(x=>x.euler.every((a,i)=>Math.abs(a-f.robot.flange_euler_rad[i])<1e-10)));
 assert.equal(p[0].path.at(-1).position[2],.3074);
 assert.ok(p[1].path.every(x=>x.position[2]===.3074));
 assert.ok(Math.abs(p[1].path.at(-1).euler[2]-.2)<1e-10);
 assert.ok(p[1].path.at(-1).euler.slice(0,2).every(x=>Math.abs(x)<1e-10));
 assert.ok(p[1].path.length>10,'orientation must be sampled, not checked only at endpoints');
});
test('preparation never descends a tool already above safe height and skips a level tool',()=>{
 const f=fixture();Object.assign(f.config,{orientationMode:'horizontal',autoLevelBeforeDepth:true,safeLevelSdkZM:.3064});
 f.robot.flange_position_m[2]=.4;f.robot.flange_euler_rad=[0,.4,0];
 const p=geometry.buildPreparation(f.robot,f.config);
 assert.equal(p.length,1);assert.equal(p[0].phase,'preparing_level');
 assert.ok(p[0].path.every(x=>x.position[2]===.4));
 f.robot.flange_euler_rad=[0,0,0];assert.deepEqual(geometry.buildPreparation(f.robot,f.config),[]);
});
test('unsafe or malformed preparation rejects before commands',()=>{
 for(const change of [{safeLevelSdkZM:NaN},{safeLevelSdkZM:.7},{autoLevelBeforeDepth:'true'},
  {orientationMode:'preserve'}]){
  const f=fixture();Object.assign(f.config,{orientationMode:'horizontal',autoLevelBeforeDepth:true,safeLevelSdkZM:.3064},change);
  assert.throws(()=>geometry.validateConfig(f.config),/grasp_config_invalid/);
 }
 const f=fixture();Object.assign(f.config,{orientationMode:'horizontal',autoLevelBeforeDepth:true,safeLevelSdkZM:.3064});
 f.robot.flange_euler_rad=[0,1.3,0];assert.throws(()=>geometry.buildPreparation(f.robot,f.config),/leveling_angle_limit/);
});
