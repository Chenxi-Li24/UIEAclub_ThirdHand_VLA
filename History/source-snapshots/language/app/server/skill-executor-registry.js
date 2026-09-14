'use strict';

const PICK_SKILL = 'pick_and_place_bottle@1';

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function validatePickAndPlaceCandidate(candidate) {
  const params = candidate?.payload?.params;
  if (!params || typeof params !== 'object' || Array.isArray(params)) {
    return { ok: false, reason: 'pick_and_place_bottle@1 缺少 payload.params' };
  }
  const keys = Object.keys(params).sort();
  if (keys.length !== 2 || keys[0] !== 'destination' || keys[1] !== 'object') {
    return { ok: false, reason: '复杂 Skill 参数必须严格遵循 contracts，禁止携带动作或轨迹' };
  }
  if (params.object !== 'coke_bottle') {
    return { ok: false, reason: 'pick_and_place_bottle@1 只接受 coke_bottle' };
  }
  const destination = params.destination;
  if (!destination || typeof destination !== 'object' || Array.isArray(destination)) {
    return { ok: false, reason: 'destination 必须是 contracts 定义的对象' };
  }
  const destinationKeys = Object.keys(destination).sort();
  if (
    destinationKeys.length !== 2 ||
    destinationKeys[0] !== 'id' ||
    destinationKeys[1] !== 'type' ||
    destination.id !== 'drop_zone_b' ||
    destination.type !== 'configured_drop_zone'
  ) {
    return { ok: false, reason: '目标区域必须是 configured drop_zone_b' };
  }
  return { ok: true };
}

class SkillExecutorRegistry {
  constructor() {
    this.adapters = new Map();
    this.validators = new Map([[PICK_SKILL, validatePickAndPlaceCandidate]]);
  }

  register(skill, adapter) {
    if (typeof skill !== 'string' || !skill) throw new TypeError('skill 必须是非空字符串');
    if (!adapter || typeof adapter.start !== 'function') {
      throw new TypeError('Skill adapter 必须提供 start(context)');
    }
    if (this.adapters.has(skill)) throw new Error(`Skill adapter 已注册: ${skill}`);
    this.adapters.set(skill, adapter);
    return this;
  }

  validate(skill, candidate) {
    const validator = this.validators.get(skill);
    if (!validator) return { ok: false, reason: `没有已知 contract: ${skill}` };
    return validator(candidate);
  }

  availableSkills() {
    return [...this.adapters.keys()].sort();
  }

  dispatch(skill, context) {
    const checked = this.validate(skill, context?.candidate);
    if (!checked.ok) return { accepted: false, reason: checked.reason };
    if (context?.confirmation?.decision !== 'confirmed') {
      return { accepted: false, reason: '复杂 Skill 缺少 confirmed confirmation.decision' };
    }
    if (
      context.confirmation.candidateId !== context.candidate.candidateId ||
      context.confirmation.traceId !== context.candidate.traceId
    ) {
      return { accepted: false, reason: '复杂 Skill 的 candidateId/traceId 与确认不匹配' };
    }
    const adapter = this.adapters.get(skill);
    if (!adapter) return { accepted: false, reason: `${skill} adapter 尚未注册` };

    const request = Object.freeze({
      schemaVersion: '1.0',
      skill,
      candidate: clone(context.candidate),
      confirmation: clone(context.confirmation),
      emit: context.emit,
    });
    return { accepted: true, result: adapter.start(request) };
  }
}

module.exports = {
  PICK_SKILL,
  SkillExecutorRegistry,
  validatePickAndPlaceCandidate,
};
