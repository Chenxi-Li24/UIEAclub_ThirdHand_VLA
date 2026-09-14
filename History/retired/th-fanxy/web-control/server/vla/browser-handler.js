'use strict';

const { parseGroundingCommand, publicGroundingState } = require('./contracts');
const { MockProvider } = require('./mock-provider');
const { OpenAIProvider, providerError } = require('./openai-provider');

class DisabledProvider {
  constructor(modelId = 'disabled') {
    this.providerName = 'disabled';
    this.modelId = modelId;
  }

  async select() {
    throw providerError('provider_unavailable');
  }
}

function createGroundingProvider(vlaConfig = {}, environment = process.env) {
  const provider = vlaConfig.provider || 'disabled';
  const model = vlaConfig.model || 'gpt-5.6-terra';
  if (provider === 'disabled') return new DisabledProvider(model);
  if (provider === 'mock') return new MockProvider();
  if (provider === 'openai') {
    return new OpenAIProvider({
      apiKey: typeof environment.OPENAI_API_KEY === 'string'
        ? environment.OPENAI_API_KEY
        : '',
      model,
      timeoutMs: vlaConfig.timeoutMs || 8000,
    });
  }
  const error = new TypeError('vla_provider_invalid');
  error.code = 'vla_provider_invalid';
  throw error;
}

function rejectedState(reason) {
  return publicGroundingState({
    status: 'rejected',
    requestId: null,
    identityId: null,
    explanation: null,
    reason,
    provider: null,
    modelId: null,
    latencyMs: null,
  });
}

function createGroundingBrowserHandler({ grounding, send }) {
  if (!grounding || typeof grounding.submit !== 'function' ||
      typeof grounding.cancel !== 'function') {
    throw new TypeError('grounding submit/cancel are required');
  }
  if (typeof send !== 'function') throw new TypeError('send must be a function');

  async function handleGroundingBrowserCommand(message, operator) {
    const parsed = parseGroundingCommand(message);
    if (!parsed.accepted) {
      send(operator, rejectedState(parsed.reason));
      return { handled: true, accepted: false, reason: parsed.reason };
    }
    try {
      const pending = grounding.submit({
        operator,
        query: parsed.query,
        send: event => send(operator, event),
      });
      Promise.resolve(pending).catch(() => {
        send(operator, rejectedState('grounding_failed'));
      });
    } catch (_) {
      send(operator, rejectedState('grounding_failed'));
      return { handled: true, accepted: false, reason: 'grounding_failed' };
    }
    return { handled: true, accepted: true };
  }

  handleGroundingBrowserCommand.cancel = (operator, reason) =>
    grounding.cancel(operator, reason);
  return handleGroundingBrowserCommand;
}

module.exports = {
  DisabledProvider,
  createGroundingBrowserHandler,
  createGroundingProvider,
  rejectedState,
};
