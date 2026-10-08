'use strict';
const {randomUUID}=require('node:crypto');
const {WebSocket}=require('ws');
const {CanonicalRobotWebSocketClient}=require('../../../../tools/frames/canonical_robot_client');
const {TcpCalibrationRobotStateSource}=require('./robot-state-source');
const {TcpCalibrationSession}=require('./session');
const {TcpCalibrationArtifactStore}=require('./artifact-store');
const {runTcpSolver}=require('./solver-adapter');
const {createTcpCalibrationRoutes}=require('./routes');

function createCalibration(config,{webUrl,canMutate}){
 const client=new CanonicalRobotWebSocketClient({WebSocketImpl:WebSocket,
  url:webUrl.replace(/^http/,'ws')+'/ws',framePolicyPath:config.tcpCalibrationFramePolicyFile});
 const stateSource=new TcpCalibrationRobotStateSource({client,confirmPoseStability:true});
 const store=new TcpCalibrationArtifactStore({root:config.tcpCalibrationArtifactRoot});
 let initialState=null;
 try{initialState=store.restoreSession();}catch(error){if(error.code!=='ENOENT')throw error;}
 const solver=request=>runTcpSolver({python:config.tcpCalibrationPython,script:config.tcpCalibrationSolverScript,request});
 const session=new TcpCalibrationSession({stateSource,solver,idFactory:randomUUID,
  now:()=>new Date().toISOString(),initialState,
  thresholds:{fitRmsGreenM:.002,fitMaximumGreenM:.004,fitRmsMaximumM:.003,fitMaximumM:.005,validationMaximumM:.005}});
 const routes=createTcpCalibrationRoutes({session,store,stateSource,canMutate});
 return {routes,store,stateSource};
}
module.exports={createCalibration};
