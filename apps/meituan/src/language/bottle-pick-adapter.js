'use strict';

const { randomUUID } = require('node:crypto');

function trimBaseUrl(value, fallback) {
  const url = typeof value === 'string' && value ? value : fallback;
  return url.replace(/\/+$/, '');
}

async function jsonResponse(response) {
  let body;
  try {
    body = await response.json();
  } catch {
    body = {};
  }
  return { response, body };
}

class BottlePickAdapter {
  constructor({
    fetchImpl = globalThis.fetch,
    visionBaseUrl = 'http://127.0.0.1:3100',
    vaBaseUrl = 'http://127.0.0.1:8766',
    requestIdFactory = randomUUID,
    pollIntervalMs = 250,
    maxPollMs = 240000,
  } = {}) {
    if (typeof fetchImpl !== 'function' || typeof requestIdFactory !== 'function') {
      throw new TypeError('BottlePickAdapter dependencies are invalid');
    }
    this.fetchImpl = fetchImpl;
    this.visionBaseUrl = trimBaseUrl(
      visionBaseUrl, 'http://127.0.0.1:3100',
    );
    this.vaBaseUrl = trimBaseUrl(vaBaseUrl, 'http://127.0.0.1:8766');
    this.requestIdFactory = requestIdFactory;
    this.pollIntervalMs = pollIntervalMs;
    this.maxPollMs = maxPollMs;
  }

  start(request) {
    const task = this._run(request).catch(error => {
      request.emit({
        type: 'skill.result',
        success: false,
        status: 'failed',
        candidateId: request.candidate.candidateId,
        traceId: request.candidate.traceId,
        message: error.message || '瓶子抓取服务调用失败',
      });
      return { accepted: false, reason: error.message || 'adapter_failed' };
    });
    return task;
  }

  async _run(request) {
    const candidate = request.candidate;
    const observation = await jsonResponse(await this.fetchImpl(
      `${this.visionBaseUrl}/api/vision/observation`,
      { headers: { accept: 'application/json' } },
    ));
    const stableId = Number(observation.body.selectedStableId);
    if (!observation.response.ok || !Number.isSafeInteger(stableId)
        || stableId < 1 || stableId > 5) {
      throw new Error('请先在视觉画面中选择一个稳定瓶子目标');
    }

    const requestId = this.requestIdFactory();
    const started = await jsonResponse(await this.fetchImpl(
      `${this.vaBaseUrl}/api/va/start`,
      {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          schema: 'thirdhand.va.command.v1',
          cmd: 'start',
          target_id: stableId,
          request_id: requestId,
        }),
      },
    ));
    if (!started.response.ok || started.body.accepted !== true) {
      throw new Error(started.body.reason || '瓶子抓取运行时未就绪');
    }
    request.emit({
      type: 'skill.execution.started',
      candidateId: candidate.candidateId,
      traceId: candidate.traceId,
      requestId,
      stableId,
      message: `已锁定视觉目标 ${stableId}，开始受监督抓取`,
    });
    return this._poll(request, requestId);
  }

  async _poll(request, requestId) {
    const startedAt = Date.now();
    while (Date.now() - startedAt <= this.maxPollMs) {
      await new Promise(resolve => setTimeout(resolve, this.pollIntervalMs));
      const status = await jsonResponse(await this.fetchImpl(
        `${this.vaBaseUrl}/api/va/status`,
        { headers: { accept: 'application/json' } },
      ));
      if (!status.response.ok) throw new Error('无法读取瓶子抓取状态');
      request.emit({
        type: 'skill.execution.status',
        candidateId: request.candidate.candidateId,
        traceId: request.candidate.traceId,
        requestId,
        phase: status.body.phase || 'unknown',
      });
      if (status.body.active === true) continue;
      const completed = status.body.phase === 'complete';
      request.emit({
        type: 'skill.result',
        success: completed,
        status: completed ? 'success' : 'failed',
        candidateId: request.candidate.candidateId,
        traceId: request.candidate.traceId,
        message: completed
          ? '受监督瓶子抓取完成'
          : `瓶子抓取结束：${status.body.reason || status.body.phase || 'unknown'}`,
      });
      return { accepted: true, completed, status: status.body };
    }
    throw new Error('瓶子抓取状态等待超时，必须人工确认机械臂状态');
  }
}

module.exports = { BottlePickAdapter, jsonResponse };
