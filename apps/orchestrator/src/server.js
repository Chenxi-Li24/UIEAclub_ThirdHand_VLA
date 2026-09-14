#!/usr/bin/env node
'use strict';

const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const { WebSocket, WebSocketServer } = require('ws');
const { AuthorizationStore } = require('../../../platform/authorization');
const { TaskEngine } = require('../../../platform/task_engine');
const { createContractValidator } = require('../../../platform/contracts/src/validator');
const { createGripperProposal } = require('../../../skills/manipulation/gripper-control/src/plan');
const gripperWorker = require('../../../skills/manipulation/gripper-control/src/worker');
const { loadConfig } = require('./config');
const { PLAN_PROTOCOL, parseClientMessage } = require('./protocol');
const { createReadinessProvider } = require('./readiness');
const { RobotExecutionClient } = require('./robot-execution-client');

function sendJson(socket, payload) {
  if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify(payload));
}

function createOrchestrator(options = {}) {
  const config = { ...loadConfig(options.env), ...options };
  const clock = options.clock || Date.now;
  const readinessProvider = options.readinessProvider || createReadinessProvider({
    robotHealthUrl: `${config.robotHealthUrl.replace(/\/$/, '')}/health`,
    clock,
  });
  const robotClient = options.robotClient || new RobotExecutionClient({
    url: config.robotExecutionWsUrl,
    tokenFile: config.robotExecutionTokenFile,
  });
  const authorizationStore = new AuthorizationStore({ clock, idFactory: options.idFactory });
  const engine = new TaskEngine({
    authorizationStore,
    readinessProvider,
    clock,
    resolveSkill: skillId => {
      if (skillId !== 'manipulation.gripper-control') {
        const error = new Error('Skill is unavailable');
        error.code = 'skill_unavailable';
        throw error;
      }
      return { execute: args => gripperWorker.execute({ ...args, robotClient }) };
    },
  });
  const contracts = createContractValidator();
  const server = http.createServer(async (request, response) => {
    if (request.method === 'GET' && request.url === '/health') {
      const readiness = await readinessProvider();
      const body = JSON.stringify({ status: 'ready', serviceId: 'orchestrator', readiness });
      response.writeHead(200, { 'content-type': 'application/json', 'content-length': Buffer.byteLength(body), 'cache-control': 'no-store' });
      response.end(body);
      return;
    }
    response.writeHead(404).end();
  });
  const wss = new WebSocketServer({
    noServer: true,
    handleProtocols(protocols) { return protocols.has(PLAN_PROTOCOL) ? PLAN_PROTOCOL : false; },
  });
  const sessions = new Set();
  server.on('upgrade', (request, socket, head) => {
    if (new URL(request.url, 'http://localhost').pathname !== '/plan') return socket.destroy();
    const protocols = String(request.headers['sec-websocket-protocol'] || '').split(',').map(value => value.trim());
    if (!protocols.includes(PLAN_PROTOCOL)) {
      socket.write('HTTP/1.1 426 Upgrade Required\r\nConnection: close\r\n\r\n');
      return socket.destroy();
    }
    wss.handleUpgrade(request, socket, head, ws => wss.emit('connection', ws));
  });
  wss.on('connection', socket => {
    const session = {
      socket,
      candidateIds: new Set(),
      proposal: null,
      granting: false,
      executed: false,
      executionAbort: null,
    };
    sessions.add(session);
    socket.on('message', async data => {
      let ownsGrant = false;
      try {
        const message = parseClientMessage(data);
        if (message.type === 'candidate.submit') {
          if (session.granting || session.executionAbort || (session.proposal && !session.executed)) {
            throw Object.assign(new Error('Resolve the current proposal first'), { code: 'proposal_pending' });
          }
          const candidate = message.candidate;
          if (!candidate || session.candidateIds.has(candidate.candidateId)) throw Object.assign(new Error('Candidate is missing or duplicated'), { code: 'candidate_duplicate' });
          session.candidateIds.add(candidate.candidateId);
          const readiness = await readinessProvider();
          if (!readiness.authorizationReady) throw Object.assign(new Error('Robot or Skill is not ready'), { code: 'readiness_unavailable' });
          const proposal = createGripperProposal(candidate, { clock, idFactory: options.idFactory, readiness });
          const validation = contracts.validate('thirdhand.plan-proposal.v1', proposal);
          if (!validation.ok) throw Object.assign(new Error(JSON.stringify(validation.errors)), { code: 'proposal_invalid' });
          engine.registerProposal({ proposal });
          session.proposal = proposal;
          session.executed = false;
          sendJson(socket, { type: 'plan.proposed', proposal });
          return;
        }
        if (message.type === 'proposal.cancel') {
          if (session.granting || session.executed) throw Object.assign(new Error('Proposal can no longer be cancelled'), { code: 'proposal_cancel_unavailable' });
          if (!session.proposal || message.proposalId !== session.proposal.proposalId) throw Object.assign(new Error('Proposal does not match this session'), { code: 'proposal_unknown' });
          const proposalId = session.proposal.proposalId;
          engine.interrupt(session.proposal.plan.taskId, message.reason || 'user_rejected');
          session.proposal = null;
          sendJson(socket, { type: 'proposal.cancelled', proposalId });
          return;
        }
        if (session.granting || session.executed) throw Object.assign(new Error('Authorization was already used'), { code: 'authorization_replayed' });
        if (!session.proposal || message.proposalId !== session.proposal.proposalId) throw Object.assign(new Error('Proposal does not match this session'), { code: 'proposal_unknown' });
        session.granting = true;
        ownsGrant = true;
        const grant = await engine.grantAuthorization(message);
        sendJson(socket, { type: 'authorization.granted', authorization: grant });
        session.executed = true;
        session.executionAbort = new AbortController();
        sendJson(socket, { type: 'execution.started', taskId: grant.taskId, traceId: session.proposal.traceId });
        const result = await engine.executeAuthorized({
          authorizationId: grant.authorizationId,
          signal: session.executionAbort.signal,
        });
        sendJson(socket, { type: 'skill.result', result });
      } catch (error) {
        sendJson(socket, { type: 'plan.rejected', code: error.code || 'internal_error', message: error.message });
      } finally {
        if (ownsGrant) {
          session.granting = false;
          session.executionAbort = null;
        }
      }
    });
    socket.on('close', () => {
      sessions.delete(session);
      session.executionAbort?.abort();
      if (session.proposal) engine.interrupt(session.proposal.plan.taskId, 'browser_disconnected');
    });
  });

  let closing = false;
  return {
    engine,
    async start() {
      await new Promise((resolve, reject) => { server.once('error', reject); server.listen(config.port, config.host, resolve); });
      fs.mkdirSync(path.dirname(config.readyFile), { recursive: true });
      fs.writeFileSync(config.readyFile, `${JSON.stringify({ ready: true, serviceId: 'orchestrator', pid: process.pid })}\n`);
      return server.address();
    },
    async close() {
      if (closing) return;
      closing = true;
      for (const session of sessions) session.socket.terminate();
      robotClient.close?.();
      await new Promise(resolve => wss.close(resolve));
      await new Promise(resolve => server.listening ? server.close(resolve) : resolve());
      try { fs.unlinkSync(config.readyFile); } catch (error) { if (error.code !== 'ENOENT') throw error; }
    },
  };
}

async function main() {
  const service = createOrchestrator();
  const address = await service.start();
  console.log(`ThirdHand Orchestrator listening on ${address.address}:${address.port}`);
  let stopping = false;
  const stop = async () => { if (stopping) return; stopping = true; await service.close(); };
  process.on('SIGINT', () => stop().then(() => process.exit(0)));
  process.on('SIGTERM', () => stop().then(() => process.exit(0)));
}

if (require.main === module) main().catch(error => { console.error(error.stack || error.message); process.exitCode = 1; });

module.exports = { createOrchestrator };
