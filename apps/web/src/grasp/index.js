'use strict';
const fs=require('node:fs'),path=require('node:path'),{createHash}=require('node:crypto');
const {GraspCoordinator}=require('./coordinator');
const {WebRobotClient}=require('./robot-client');
const {validateConfig}=require('./geometry');
const {ActiveDepthCoordinator,DEFAULT_LIMITS}=require('../active-depth/coordinator');
const {VisionClient}=require('../active-depth/vision-client');
const digest=b=>'sha256:'+createHash('sha256').update(b).digest('hex');
function createFromFile(file,{ownerToken=null}={}){
 const config=JSON.parse(fs.readFileSync(file,'utf8'));validateConfig(config);
 if(config.schema!=='thirdhand-web-grasp-config-v1'||config.enabled!==true||config.legacyGraspEnabled!==false)throw new Error('grasp_config_disabled');
 const web=new URL(config.webUrl);if(web.port!=='9983')throw new Error('web_route_required');
 const read=(name,id)=>{const b=fs.readFileSync(path.resolve(path.dirname(file),config[name]));if(digest(b)!==config[id])throw new Error('artifact_hash_mismatch');return JSON.parse(b);};
 const policy=read('framePolicyFile','framePolicyId'),calibration=read('calibrationFile','calibrationId');
 if(policy.source_semantics!=='sdk_tool_mislabeled_as_robot_flange'||policy.T_flange_sdk_tool[0][3]!==config.sdkToolOffsetM||
  calibration.numerically_validated!==true||calibration.frame_normalization?.policy_id!==config.framePolicyId)throw new Error('frame_binding_mismatch');
 for(const b of policy.bindings)if(digest(fs.readFileSync(b.path))!=='sha256:'+b.sha256)throw new Error('runtime_binding_changed');
 // This hash-bound bridge intentionally publishes feedback only at motion boundaries.
 const robotClient=new WebRobotClient({url:config.webUrl.replace(/^http/,'ws')+'/ws',jointLimits:config.jointLimits,stateMaxAgeMs:config.stateMaxAgeMs,deferConnect:true,terminalFeedbackOnly:true,ownerToken});
 const visionClient=new VisionClient({baseUrl:config.webUrl});
 const mount={matrix_4x4:calibration.T_flange_camera.matrix_4x4,...calibration.camera};
 const depthCoordinator=new ActiveDepthCoordinator({visionClient,executionClient:robotClient,getRobotState:()=>robotClient.state({idle:true}),mount,
  limits:{...DEFAULT_LIMITS,maxStepDeg:1,maxArmStepDeg:0.5,maxCumulativeJointDeg:10,maxArmCumulativeJointDeg:5,jointLimitsDeg:config.jointLimits}});
 const auditDir=path.resolve(path.dirname(file),'../../../artifacts/diagnostics/web-grasp-20261006/sessions');fs.mkdirSync(auditDir,{recursive:true});
 const controller=new GraspCoordinator({config,robotClient,visionClient,depthCoordinator,audit:event=>{
  if(event.sessionId)fs.appendFileSync(path.join(auditDir,event.sessionId+'.jsonl'),JSON.stringify(event)+'\n');
 }});
 return controller;
}
module.exports={createFromFile};
