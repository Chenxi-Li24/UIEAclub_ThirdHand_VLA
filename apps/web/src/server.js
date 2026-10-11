#!/usr/bin/env node
'use strict';

const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const { randomUUID } = require('node:crypto');
const { WebSocketServer } = require('ws');
const { loadConfig } = require('./config');
const { proxyHttpRequest } = require('./http-proxy');
const { RobotProxy } = require('./robot-proxy');
const { serveStatic } = require('./static-server');
const { VisionProxy } = require('./vision-proxy');
const { WebSocketProxy } = require('./websocket-proxy');
const { ActiveDepthCoordinator } = require('./active-depth/coordinator');
const { ExecutionClient } = require('./active-depth/execution-client');
const { VisionClient } = require('./active-depth/vision-client');
const { DummyController } = require('./dummy-controller');
const VOICE_PROTOCOL = 'thirdhand.voice.v1';

function writeJson(response, status, payload) {
  const body = JSON.stringify(payload);
  response.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'content-length': Buffer.byteLength(body),
    'cache-control': 'no-store',
  });
  response.end(body);
}

function readJson(request, maximumBytes = 16 * 1024) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    let tooLarge = false;
    request.on('data', chunk => {
      size += chunk.length;
      if (size > maximumBytes) tooLarge = true;
      else chunks.push(chunk);
    });
    request.on('end', () => {
      if (tooLarge) {
        const error = new Error('Request body is too large');
        error.code = 'body_too_large';
        reject(error);
        return;
      }
      try { resolve(JSON.parse(Buffer.concat(chunks).toString('utf8'))); }
      catch {
        const error = new Error('Request body is invalid JSON');
        error.code = 'invalid_json';
        reject(error);
      }
    });
    request.on('error', reject);
  });
}

function loadMount(file) {
  const document = JSON.parse(fs.readFileSync(file, 'utf8'));
  return {
    matrix_4x4: document.matrix_4x4 || document.T_flange_camera?.matrix_4x4,
    camera_mount_id: document.camera_mount_id || document.camera?.camera_mount_id,
    registration_id: document.registration_id || document.camera?.registration_id,
    physicalValidation: document.physical_validation?.status || null,
  };
}

function exactKeys(body, keys) {
  return body && typeof body === 'object' && !Array.isArray(body)
    && Object.keys(body).length === keys.length
    && keys.every(key => Object.prototype.hasOwnProperty.call(body, key));
}

function createWebGateway(options = {}) {
  const config = { ...loadConfig(options.env), ...options };
  const dummyController = options.dummyController || new DummyController(config);
  const robotProxy = options.robotProxy || new RobotProxy(config.robotWsUrl, config.language);
  const visionProxy = options.visionProxy || new VisionProxy(config.visionWsUrl);
  const voiceProxy = options.voiceProxy || new WebSocketProxy(config.voiceWsUrl, {
    subprotocol: VOICE_PROTOCOL,
  });
  let coordinator = options.coordinator;
  let activeDepthReason = null;
  if (!coordinator) {
    try {
      const mount = loadMount(config.activeDepthMountFile);
      const executionClient = new ExecutionClient({
        endpoint: config.robotExecutionWsUrl,
        tokenFile: config.robotExecutionTokenFile,
      });
      const visionClient = new VisionClient({ baseUrl: config.visionHttpUrl });
      coordinator = new ActiveDepthCoordinator({
        executionClient, visionClient, mount,
        getRobotState: () => robotProxy.getRobotState(),
      });
    } catch (error) {
      activeDepthReason = error.code || 'active_depth_configuration_invalid';
    }
  }
  let activeDepthReady = Boolean(coordinator);
  const graspEnv = options.env || process.env;
  const graspOwnerToken = options.graspOwnerToken || randomUUID();
  let graspController = options.graspController || null;
  let graspReason = null;
  const webUrl=graspEnv.WEB_GRASP_WEB_URL || `http://${['0.0.0.0','::'].includes(config.host)?'127.0.0.1':config.host}:${config.port}`;
  let tcpCalibrationRoutes=options.tcpCalibrationRoutes||null;
  let tcpStore=options.tcpStore||null;
  let tcpStateSource=null;
  let tcpCalibrationReason=tcpCalibrationRoutes?null:'tcp_calibration_disabled';
  if(!tcpCalibrationRoutes&&config.tcpCalibrationEnabled){
    try{
      const tcp=require('./tcp-calibration').createCalibration(config,{webUrl,
        onArtifactsChanged:()=>robotProxy.broadcast(graspConfiguration()),
        canMutate:()=>!graspController?.status().active&&!coordinator?.status().active&&!robotProxy.hasActiveControl?.()});
      tcpCalibrationRoutes=tcp.routes;tcpStore=tcp.store;tcpStateSource=tcp.stateSource;tcpCalibrationReason=null;
    }catch(error){tcpCalibrationReason=error.code||error.message||'tcp_calibration_configuration_invalid';}
  }
  if (!graspController && graspEnv.WEB_GRASP_CONFIG) {
    try {
      const factory = require(graspEnv.WEB_GRASP_MODULE || './grasp');
      graspController = factory.createFromFile(graspEnv.WEB_GRASP_CONFIG,{ownerToken:graspOwnerToken,webUrl,tcpStore});
    } catch (error) { graspReason = error.code || error.message || 'grasp_configuration_invalid'; }
  }
  if(graspController?.motionConfiguration?.().orientationMode==='horizontal'&&graspController.depthCoordinator){
    coordinator?.close();coordinator=graspController.depthCoordinator;activeDepthReady=true;activeDepthReason=null;
  }
  function graspConfiguration(){
    let tcp=null,reason=graspReason;
    try{tcp=graspController?.tcpConfiguration?.()||null;}catch(error){reason=error.code||error.message||'tcp_unavailable';}
    return {type:'grasp.config',enabled:Boolean(graspController)&&!reason,
      gripOffsetM:graspController?.status().gripOffsetM||null,legacyGraspEnabled:false,
      startEndpoint:'/api/grasp/start',reason,tcp,motion:graspController?.motionConfiguration?.()||null,calibrationPage:'/tcp-calibration.html'};
  }
  robotProxy.setGraspInterlock?.(() => graspController?.status().active?graspController.status():coordinator?.status());
  visionProxy.canForward = browser => {
    if (!graspController?.status().active&&!coordinator?.status().active) return true;
    if (browser.readyState === browser.OPEN) browser.send(JSON.stringify({type:'error',code:'grasp_active'}));
    return false;
  };
  if (graspController) graspController.on('status', status => robotProxy.broadcast(status));
  const connections = new Set();
  let closing = false;

  if (coordinator) coordinator.on('status', status => robotProxy.broadcast(status));

  const server = http.createServer(async (request, response) => {
    const pathname = new URL(request.url, 'http://localhost').pathname;
    if (request.method === 'GET' && pathname === '/api/runtime-config') {
      writeJson(response, 200, {
        voice: { endpoint: '/voice', protocol: VOICE_PROTOCOL },
        vision: { endpoint: '/vision' },
        activeDepth: { ready: activeDepthReady, startEndpoint: '/api/active-depth/start' },
        dummy: { statusEndpoint: '/api/dummy/status', startEndpoint: '/api/dummy/start',
          stopEndpoint: '/api/dummy/stop', frameEndpoint: '/api/dummy/frame' },
        grasp: graspConfiguration(),
        tcpCalibration: tcpCalibrationRoutes?.config()||{ready:false,reason:tcpCalibrationReason,page:'/tcp-calibration.html'},
        language: {
          executionBackend: 'formal-3000-upstream',
          directional: {
            enabled: config.language.directionalEnabled,
            realControlEnabled: config.language.directionalRealControlEnabled,
          },
        },
      });
      return;
    }
    if (request.method === 'GET' && pathname === '/health') {
      writeJson(response, 200, {
        status: 'ready',
        serviceId: 'web',
        dependencies: {
          robot: { url: config.robotWsUrl },
          vision: { url: config.visionHttpUrl },
          voice: { url: config.voiceWsUrl },
          bottlePick: { url: config.language.vaHttpUrl },
          activeDepth: { ready: activeDepthReady, reason: activeDepthReason },
          grasp: graspConfiguration(),
          tcpCalibration: tcpCalibrationRoutes?.config()||{ready:false,reason:tcpCalibrationReason},
        },
      });
      return;
    }
    if (pathname.startsWith('/api/dummy/')) {
      try {
        if (request.method === 'GET' && pathname === '/api/dummy/status') {
          writeJson(response, 200, await dummyController.status());
          return;
        }
        if (request.method === 'GET' && pathname === '/api/dummy/frame') {
          writeJson(response, 200, await dummyController.frame());
          return;
        }
        if (request.method !== 'POST' || !['/api/dummy/start', '/api/dummy/stop'].includes(pathname)) {
          writeJson(response, 404, { error: 'not_found' });
          return;
        }
        let sameOrigin = true;
        try {
          if (request.headers.origin) {
            const origin = new URL(request.headers.origin);
            sameOrigin = ['http:', 'https:'].includes(origin.protocol) && origin.host === request.headers.host;
          }
        } catch { sameOrigin = false; }
        if (!sameOrigin || request.headers['sec-fetch-site'] === 'cross-site') {
          writeJson(response, 403, { error: 'dummy_origin_rejected' });
          return;
        }
        if (!String(request.headers['content-type'] || '').startsWith('application/json')) {
          writeJson(response, 415, { error: 'json_required' });
          return;
        }
        const body = await readJson(request);
        if (pathname.endsWith('/start')) {
          if (!exactKeys(body, ['authorized', 'keywords']) || typeof body.authorized !== 'boolean'
              || typeof body.keywords !== 'boolean') {
            writeJson(response, 400, { error: 'request_invalid' });
            return;
          }
          writeJson(response, 202, await dummyController.start(body));
        } else {
          if (!exactKeys(body, [])) {
            writeJson(response, 400, { error: 'request_invalid' });
            return;
          }
          writeJson(response, 202, dummyController.stop());
        }
      } catch (error) {
        const code = error.code || 'dummy_request_failed';
        const status = code === 'body_too_large' ? 413 : code === 'invalid_json' ? 400
          : code === 'dummy_authorization_required' ? 403
            : ['dummy_already_running', 'dummy_external_process', 'dummy_robot_busy',
              'dummy_start_pending', 'dummy_backend_upgrade_required'].includes(code) ? 409 : 503;
        if (!response.headersSent) writeJson(response, status, { error: code });
      }
      return;
    }
    if (request.method === 'GET' && pathname === '/api/grasp/status') {
      writeJson(response, 200, graspController?.status() || {
        type: 'grasp.status', phase: 'unavailable', active: false,
        reason: graspReason || 'grasp_unavailable', legacyGraspEnabled: false,
      });
      return;
    }
    if(pathname.startsWith('/api/tcp-calibration/')){
      if(!tcpCalibrationRoutes){writeJson(response,503,{error:tcpCalibrationReason});return;}
      await tcpCalibrationRoutes.handle(request,response,pathname);return;
    }
    if (request.method === 'POST' && ['/api/grasp/start', '/api/grasp/stop'].includes(pathname)) {
      if (request.headers.origin) {
        try {
          if (new URL(request.headers.origin).host !== request.headers.host) {
            writeJson(response, 403, {error:'origin_not_allowed'}); return;
          }
        } catch { writeJson(response, 403, {error:'origin_not_allowed'}); return; }
      }
      if (!graspController) { writeJson(response, 503, {error:graspReason || 'grasp_unavailable'}); return; }
      try {
        const body = await readJson(request);
        if (pathname.endsWith('/start')) {
          if (robotProxy.hasActiveControl?.() && !graspController.status().active) {
            writeJson(response,409,{error:'robot_control_busy'});return;
          }
          if (!exactKeys(body, ['stableId','requestId']) || !Number.isSafeInteger(body.stableId)
              || body.stableId < 1 || body.stableId > 5 || typeof body.requestId !== 'string'
              || !/^[\w:-]{1,120}$/.test(body.requestId)) {
            writeJson(response, 400, {error:'request_invalid'}); return;
          }
          if (coordinator?.status().active) { writeJson(response, 409, {error:'active_depth_active'}); return; }
          if(tcpStateSource?.snapshot().teachActive||tcpStateSource?.teachTransition){writeJson(response,409,{error:'tcp_calibration_teaching'});return;}
          writeJson(response, 202, await graspController.start(body.stableId,body.requestId));
        } else {
          if (!exactKeys(body, ['sessionId']) || typeof body.sessionId !== 'string' || !body.sessionId) {
            writeJson(response, 400, {error:'request_invalid'}); return;
          }
          writeJson(response, 200, await graspController.stop(body.sessionId));
        }
      } catch (error) {
        const status = error.code === 'body_too_large' ? 413
          : ['grasp_active','request_id_conflict'].includes(error.code) ? 409
          : ['request_invalid','invalid_json'].includes(error.code) ? 400
          : /artifact|candidate|tcp_/.test(error.code||error.message||'') ? 503 : 500;
        writeJson(response,status,{error:error.code || error.message || 'grasp_error'});
      }
      return;
    }
    if (request.method === 'GET' && pathname === '/api/active-depth/status') {
      writeJson(response, 200, coordinator?.status() || {
        type: 'active_depth.status', phase: 'unavailable', active: false,
        reason: activeDepthReason || 'active_depth_unavailable',
      });
      return;
    }
    if (request.method === 'POST'
        && (pathname === '/api/active-depth/start' || pathname === '/api/active-depth/stop')) {
      if(request.headers.origin){
        try{if(new URL(request.headers.origin).host!==request.headers.host){writeJson(response,403,{error:'origin_not_allowed'});return;}}
        catch{writeJson(response,403,{error:'origin_not_allowed'});return;}
      }
      if (!coordinator) {
        writeJson(response, 503, { error: activeDepthReason || 'active_depth_unavailable' });
        return;
      }
      try {
        const body = await readJson(request);
        if (pathname.endsWith('/start')) {
          if (graspController?.status().active) {
            writeJson(response, 409, {error:'grasp_active'}); return;
          }
          if(robotProxy.hasActiveControl?.()){writeJson(response,409,{error:'robot_control_busy'});return;}
          if(tcpStateSource?.snapshot().teachActive||tcpStateSource?.teachTransition){writeJson(response,409,{error:'tcp_calibration_teaching'});return;}
          if (!exactKeys(body, ['stableId']) || !Number.isSafeInteger(body.stableId)
              || body.stableId < 1 || body.stableId > 5) {
            writeJson(response, 400, { error: 'request_invalid' });
            return;
          }
          writeJson(response, 202, await coordinator.start(body.stableId));
          return;
        }
        if (!exactKeys(body, ['sessionId']) || typeof body.sessionId !== 'string'
            || body.sessionId.length === 0) {
          writeJson(response, 400, { error: 'request_invalid' });
          return;
        }
        writeJson(response, 200, await coordinator.stop(body.sessionId));
      } catch (error) {
        if (response.headersSent) return;
        const status = error.code === 'body_too_large' ? 413
          : error.code === 'active_depth_active' ? 409
            : ['invalid_json', 'stable_id_invalid'].includes(error.code) ? 400 : 500;
        writeJson(response, status, { error: error.code || 'active_depth_error' });
      }
      return;
    }
    const visionGetRoutes = new Set([
      '/api/vision/status',
      '/api/vision/observation',
      '/camera/xvisio/raw',
      '/camera/xvisio/vision',
      '/camera/xvisio/depth',
    ]);
    const visionPostRoutes = new Set([
      '/api/vision/select',
      '/api/vision/release',
    ]);
    const isVisionTargetRoute = pathname.startsWith('/api/vision/targets/')
      && /^[1-5]$/.test(pathname.slice('/api/vision/targets/'.length));
    if ((request.method === 'GET' && (visionGetRoutes.has(pathname) || isVisionTargetRoute)) ||
        (request.method === 'POST' && visionPostRoutes.has(pathname))) {
      if (request.method === 'POST' && (graspController?.status().active||coordinator?.status().active)) {
        writeJson(response,409,{error:'grasp_active'});return;
      }
      proxyHttpRequest(request, response, config.visionHttpUrl, pathname);
      return;
    }
    if (serveStatic(request, response, config)) return;
    writeJson(response, 404, { error: 'not_found' });
  });
  server.on('connection', socket => {
    connections.add(socket);
    socket.once('close', () => connections.delete(socket));
  });

  const robotWss = new WebSocketServer({ noServer: true });
  const visionWss = new WebSocketServer({ noServer: true });
  const voiceWss = new WebSocketServer({
    noServer: true,
    handleProtocols(protocols) {
      return protocols.has(VOICE_PROTOCOL) ? VOICE_PROTOCOL : false;
    },
  });
  server.on('upgrade', (request, socket, head) => {
    if (request.url === '/ws') {
      robotWss.handleUpgrade(
        request,
        socket,
        head,
        ws => robotWss.emit('connection', ws, request),
      );
      return;
    }
    if (request.url === '/vision') {
      visionWss.handleUpgrade(
        request,
        socket,
        head,
        ws => visionWss.emit('connection', ws),
      );
      return;
    }
    if (request.url !== '/voice') {
      socket.destroy();
      return;
    }
    const requestedProtocols = String(
      request.headers['sec-websocket-protocol'] || '',
    ).split(',').map(value => value.trim());
    if (!requestedProtocols.includes(VOICE_PROTOCOL)) {
      socket.write('HTTP/1.1 426 Upgrade Required\r\n\r\n');
      socket.destroy();
      return;
    }
    voiceWss.handleUpgrade(
      request,
      socket,
      head,
      ws => voiceWss.emit('connection', ws),
    );
  });
  robotWss.on('connection', (socket, request) => {
    robotProxy.attach(socket,{graspOwner:request?.headers['x-thirdhand-grasp-owner']===graspOwnerToken});
    if (coordinator && socket.readyState === socket.OPEN) {
      socket.send(JSON.stringify(coordinator.status()));
    }
    if (socket.readyState === socket.OPEN) {
      socket.send(JSON.stringify(graspConfiguration()));
      if (graspController) socket.send(JSON.stringify(graspController.status()));
    }
  });
  visionWss.on('connection', socket => visionProxy.attach(socket));
  voiceWss.on('connection', socket => voiceProxy.attach(socket));

  return {
    async start() {
      await new Promise((resolve, reject) => {
        server.once('error', reject);
        server.listen(config.port, config.host, resolve);
      });
      fs.mkdirSync(path.dirname(config.readyFile), { recursive: true });
      fs.writeFileSync(config.readyFile, `${JSON.stringify({
        ready: true,
        serviceId: 'web',
        pid: process.pid,
      })}\n`);
      if(tcpStateSource&&config.port===0){
        const address=server.address(),host=['0.0.0.0','::'].includes(config.host)?'127.0.0.1':config.host;
        tcpStateSource.client.url=`ws://${host}:${address.port}/ws`;
      }
      tcpCalibrationRoutes?.connect?.();
      return server.address();
    },
    async close() {
      if (closing) return;
      closing = true;
    await dummyController.close();
    await tcpCalibrationRoutes?.close?.();
    if (graspController) await graspController.close();
      if (coordinator) await coordinator.close();
      robotProxy.close();
      visionProxy.close();
      voiceProxy.close();
      // MJPEG responses are intentionally long-lived. Tear down every inbound
      // transport so an active camera feed cannot block a supervised stop.
      for (const socket of connections) socket.destroy();
      await new Promise(resolve => robotWss.close(resolve));
      await new Promise(resolve => visionWss.close(resolve));
      await new Promise(resolve => voiceWss.close(resolve));
      await new Promise(resolve => server.listening ? server.close(resolve) : resolve());
      try {
        fs.unlinkSync(config.readyFile);
      } catch (error) {
        if (error.code !== 'ENOENT') throw error;
      }
    },
  };
}

async function main() {
  const gateway = createWebGateway();
  const address = await gateway.start();
  console.log(`ThirdHand Web Gateway listening on http://${address.address}:${address.port}`);

  let stopping = false;
  const stop = async () => {
    if (stopping) return;
    stopping = true;
    await gateway.close();
  };
  process.on('SIGINT', () => stop().then(() => process.exit(0)));
  process.on('SIGTERM', () => stop().then(() => process.exit(0)));
}

if (require.main === module) {
  main().catch(error => {
    console.error(error.stack || error.message);
    process.exitCode = 1;
  });
}

module.exports = { createWebGateway, exactKeys, loadMount, readJson };
