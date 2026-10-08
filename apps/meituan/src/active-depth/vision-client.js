'use strict';

function visionError(code, message) {
  const error = new Error(message);
  error.code = code;
  return error;
}

function validateBaseUrl(baseUrl) {
  const url = new URL(baseUrl);
  if (!['http:', 'https:'].includes(url.protocol)) {
    throw visionError('vision_endpoint_invalid', 'Vision endpoint must use HTTP');
  }
  return url.toString().replace(/\/$/, '');
}

async function readJson(response) {
  const text = await response.text();
  if (text.length > 1024 * 1024) throw visionError('vision_response_too_large', 'Vision response is too large');
  if (!response.ok) throw visionError('vision_unavailable', `Vision request failed with ${response.status}`);
  try { return JSON.parse(text); }
  catch { throw visionError('vision_response_invalid', 'Vision response is not valid JSON'); }
}

class VisionClient {
  constructor({ baseUrl, fetchImpl = fetch }) {
    this.baseUrl = validateBaseUrl(baseUrl);
    this.fetchImpl = fetchImpl;
  }

  async snapshot(stableId) {
    if (!Number.isSafeInteger(stableId) || stableId < 1 || stableId > 5) {
      throw visionError('vision_target_invalid', 'Stable target ID must be within 1..5');
    }
    const [observationResponse, statusResponse] = await Promise.all([
      this.fetchImpl(`${this.baseUrl}/api/vision/observation`),
      this.fetchImpl(`${this.baseUrl}/api/vision/status`),
    ]);
    const [observation, status] = await Promise.all([
      readJson(observationResponse), readJson(statusResponse),
    ]);
    const runtimeEvidence = status.runtimeEvidence || {};
    const detection = status.detection || {};
    const detectionFrameId = Number(detection.frame_id ?? detection.frameId);
    const detectionEvidenceId = detection.evidence_id ?? detection.evidenceId;
    if (!Number.isSafeInteger(detectionFrameId) || detectionFrameId < 0
        || !/^sha256:[0-9a-f]{64}$/.test(String(detectionEvidenceId))) {
      throw visionError('vision_evidence_mismatch', 'Vision status has no correlated detection evidence');
    }
    const observationFrameId = Number(observation.frameId ?? observation.frame_id);
    let effectiveObservation = observation;
    if (detectionFrameId !== observationFrameId) {
      if (!Array.isArray(detection.targets)) {
        throw visionError('vision_evidence_mismatch', 'Vision status evidence cannot supply its detection frame');
      }
      effectiveObservation = {
        ...detection,
        frameId: detectionFrameId,
        observedAtMs: Number(detection.ts) || Date.now(),
        selectedStableId: detection.selectedStableId ?? detection.selected_stable_id,
        robotControlEnabled: observation.robotControlEnabled,
      };
    }
    if (Number(effectiveObservation.selectedStableId) !== stableId) {
      throw visionError('vision_target_mismatch', 'Vision selection changed');
    }
    const matches = (effectiveObservation.targets || []).filter(target =>
      Number(target.stable_id ?? target.stableId) === stableId);
    if (matches.length !== 1) {
      throw visionError('vision_target_mismatch', 'Selected target is not unique');
    }
    const frameId = Number(effectiveObservation.frameId ?? effectiveObservation.frame_id);
    if (!Number.isSafeInteger(frameId) || frameId < 0) {
      throw visionError('vision_frame_invalid', 'Vision frame ID is invalid');
    }
    const correlatedEvidence = {
      evidence_id: detectionEvidenceId,
      motion_epoch: Number(detection.motion_epoch ?? detection.motionEpoch ?? 0),
    };
    return {
      observation: Object.freeze({ ...effectiveObservation, frameId, ...runtimeEvidence, ...correlatedEvidence }),
      runtimeEvidence: Object.freeze({ ...runtimeEvidence }),
    };
  }
}

module.exports = { VisionClient, readJson, validateBaseUrl };
