'use strict';

const PROMPT_VERSION = 'thirdhand-grounding-v1';

const SYSTEM_PROMPT = [
  'You are the semantic target grounder for a robot vision research preview.',
  'The image contains authoritative ID#N overlays and the user message contains the only allowed candidates.',
  'Select only one enumerated identity when the requested object is visually supported.',
  'Use clarify when multiple candidates plausibly match, and none when no candidate matches.',
  'Never invent an identity, coordinate, pose, trajectory, action, or safety claim.',
].join(' ');

function decisionSchema(allowedIdentityIds) {
  if (!Array.isArray(allowedIdentityIds) || allowedIdentityIds.length < 1 ||
      allowedIdentityIds.some(value => !Number.isSafeInteger(value) || value < 0) ||
      new Set(allowedIdentityIds).size !== allowedIdentityIds.length) {
    throw new TypeError('allowed identity IDs are invalid');
  }
  return {
    type: 'object',
    additionalProperties: false,
    required: ['decision', 'identity_id', 'ambiguous', 'explanation', 'semantic_score'],
    properties: {
      decision: { type: 'string', enum: ['select', 'clarify', 'none'] },
      identity_id: {
        anyOf: [
          { type: 'integer', enum: [...allowedIdentityIds] },
          { type: 'null' },
        ],
      },
      ambiguous: { type: 'boolean' },
      explanation: { type: 'string', minLength: 1, maxLength: 512 },
      semantic_score: {
        anyOf: [
          { type: 'number', minimum: 0, maximum: 1 },
          { type: 'null' },
        ],
      },
    },
  };
}

function renderUserPrompt(query, candidates) {
  const allowed = candidates.map(candidate => ({
    identity_id: candidate.identityId,
    detection_id: candidate.detectionId,
    label: candidate.label,
    identity_status: candidate.identityStatus,
    detection_score: candidate.detectionScore,
  }));
  return [
    `Natural-language request: ${JSON.stringify(query)}`,
    `Allowed candidates: ${JSON.stringify(allowed)}`,
    'Return a schema-valid advisory decision. This preview cannot execute robot motion.',
  ].join('\n');
}

function buildOpenAIRequest({ query, evidence, model }) {
  if (typeof query !== 'string' || !query.trim()) throw new TypeError('query is required');
  if (typeof model !== 'string' || !/^[A-Za-z0-9._-]{1,128}$/.test(model)) {
    throw new TypeError('model is invalid');
  }
  if (!evidence || !Buffer.isBuffer(evidence.jpeg) ||
      !Array.isArray(evidence.candidates) || !Array.isArray(evidence.allowedIdentityIds)) {
    throw new TypeError('validated evidence is required');
  }
  const candidateIds = evidence.candidates.map(candidate => candidate.identityId);
  if (candidateIds.length !== evidence.allowedIdentityIds.length ||
      candidateIds.some((identityId, index) => identityId !== evidence.allowedIdentityIds[index])) {
    throw new TypeError('evidence identity enumeration is inconsistent');
  }
  return {
    model,
    reasoning: { effort: 'low' },
    store: false,
    input: [
      {
        role: 'system',
        content: [{ type: 'input_text', text: SYSTEM_PROMPT }],
      },
      {
        role: 'user',
        content: [
          { type: 'input_text', text: renderUserPrompt(query.trim(), evidence.candidates) },
          {
            type: 'input_image',
            image_url: `data:image/jpeg;base64,${evidence.jpeg.toString('base64')}`,
            detail: 'low',
          },
        ],
      },
    ],
    text: {
      format: {
        type: 'json_schema',
        name: 'thirdhand_target_selection',
        strict: true,
        schema: decisionSchema(evidence.allowedIdentityIds),
      },
    },
    max_output_tokens: 300,
  };
}

module.exports = {
  PROMPT_VERSION,
  SYSTEM_PROMPT,
  buildOpenAIRequest,
  decisionSchema,
  renderUserPrompt,
};
