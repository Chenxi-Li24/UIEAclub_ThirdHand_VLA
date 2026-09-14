'use strict';

(function exposeActiveViewDemo(root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.ThirdHandActiveViewDemo = api;
}(typeof globalThis === 'object' ? globalThis : this, function buildActiveViewDemoApi() {
  const SESSION_ID = '11111111-1111-4111-8111-111111111111';
  const COARSE_PROPOSAL_ID = '22222222-2222-4222-8222-222222222222';
  const REFINE_PROPOSAL_ID = '33333333-3333-4333-8333-333333333333';
  const TARGET_ID = 7;

  function clone(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function exactKeys(value, expected) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
    const actual = Object.keys(value).sort();
    const wanted = [...expected].sort();
    return actual.length === wanted.length && actual.every((key, index) => key === wanted[index]);
  }

  function svgPanel(title, subtitle, body, accent) {
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="960" height="540" viewBox="0 0 960 540">
      <rect width="960" height="540" fill="#081017"/>
      <rect x="28" y="28" width="904" height="484" rx="18" fill="#101b24" stroke="#29404e" stroke-width="3"/>
      <text x="60" y="84" fill="#eef3f6" font-family="sans-serif" font-size="28" font-weight="700">${title}</text>
      <text x="60" y="116" fill="#91a1ad" font-family="sans-serif" font-size="18">${subtitle}</text>
      <rect x="250" y="150" width="460" height="300" rx="16" fill="#182630" stroke="${accent}" stroke-width="4" stroke-dasharray="12 8"/>
      <ellipse cx="480" cy="302" rx="72" ry="112" fill="${accent}" fill-opacity=".24" stroke="${accent}" stroke-width="5"/>
      <circle cx="480" cy="302" r="9" fill="#ffffff"/>
      <line x1="445" y1="302" x2="515" y2="302" stroke="#ffffff" stroke-width="3"/>
      <line x1="480" y1="267" x2="480" y2="337" stroke="#ffffff" stroke-width="3"/>
      <text x="480" y="486" text-anchor="middle" fill="#dbe9f2" font-family="sans-serif" font-size="20">${body}</text>
      <text x="900" y="82" text-anchor="end" fill="#ffbd5b" font-family="sans-serif" font-size="18" font-weight="700">SIMULATION ONLY</text>
    </svg>`;
    return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
  }

  const cameraPanels = Object.freeze({
    lumos: svgPanel(
      'Lumos 广角目标视图',
      'RTMDet mask · REMIND identity #7 · DINO similarity 93%',
      '合成瓶子目标 · 鱼眼负责发现与身份连续性',
      '#52a8df'
    ),
    d435: svgPanel(
      'D435 中央深度质量区',
      'central ROI 60% · stable depth samples',
      '合成深度点 · D435 负责近场度量',
      '#6ee7a0'
    ),
  });

  function baseTarget() {
    return {
      identityId: TARGET_ID,
      identityStatus: 'confirmed',
      identityMemory: {
        hits: 8,
        workPrototypeCount: 4,
        stablePrototypeCount: 3,
        appearanceSimilarity: 0.93,
        associationCost: 0.07,
        associationReason: 'matched_demo_prototype',
      },
      label: 'bottle',
      score: 0.96,
      positionM: null,
      reasons: ['simulation_only'],
      actionable: false,
    };
  }

  function emptyControl() {
    return {
      phase: 'idle',
      sessionId: null,
      identityId: null,
      proposalId: null,
      requestId: null,
      reasons: ['simulation_only'],
      evidenceIdsShort: [],
      moveReady: false,
      kind: null,
      targetPoseId: null,
      maxStepM: null,
      requiresConfirmation: true,
    };
  }

  function initialState() {
    return {
      online: true,
      modelReady: true,
      d435Ready: true,
      lumosReady: true,
      roles: {
        canonicalRgb: 'lumos_rgb',
        metricDepth: 'd435_depth',
        debugRgb: 'd435_rgb',
      },
      sequences: { lumos: 1001, d435: 2001 },
      metrics: { latencyMs: 24.1, latencyP95Ms: 31.8, gpuMemoryReservedGib: 0.47 },
      targets: [baseTarget()],
      blockers: ['simulation_only', 'physical_calibration_unavailable'],
      sourceAgeMs: 0,
      stale: false,
      taskCheckpointValidated: false,
      robotExecutionEnabled: false,
      activeViewExecutionEnabled: false,
      activeViewExecutionRequested: false,
      activeView: {
        executionEnabled: false,
        executionRequested: false,
        reports: [],
        control: emptyControl(),
      },
      error: null,
    };
  }

  function reportFor(stage) {
    if (stage === 0) {
      return {
        detectionId: 701,
        identityId: TARGET_ID,
        kind: 'coarse_pose',
        targetPoseId: 'demo_table_center',
        expiresNs: 999999999999999,
        coarseCenterXYM: [0.342, -0.118],
        validDepthPoints: 0,
        centralFraction: 0.16,
        depthAcceptable: false,
        stableSamples: 0,
        remainingRefinements: 1,
        reasons: ['d435_target_not_centered'],
        executionEnabled: false,
      };
    }
    if (stage === 1) {
      return {
        detectionId: 702,
        identityId: TARGET_ID,
        kind: 'refine_delta',
        targetPoseId: 'demo_refine_left_15mm',
        expiresNs: 999999999999999,
        coarseCenterXYM: [0.342, -0.118],
        validDepthPoints: 184,
        centralFraction: 0.48,
        depthAcceptable: false,
        stableSamples: 2,
        remainingRefinements: 0,
        reasons: ['depth_samples_unstable'],
        executionEnabled: false,
      };
    }
    return {
      detectionId: 703,
      identityId: TARGET_ID,
      kind: 'none',
      targetPoseId: null,
      expiresNs: 999999999999999,
      coarseCenterXYM: [0.342, -0.118],
      validDepthPoints: 612,
      centralFraction: 0.92,
      depthAcceptable: true,
      stableSamples: 5,
      remainingRefinements: 0,
      reasons: [],
      executionEnabled: false,
    };
  }

  function createActiveViewDemo() {
    let state = initialState();
    let stage = -1;
    const listeners = new Set();

    function snapshot() {
      return clone(state);
    }

    function notify() {
      const value = snapshot();
      for (const listener of listeners) listener(value);
    }

    function reject(reason) {
      return { accepted: false, reason: String(reason).slice(0, 128) };
    }

    function start(command) {
      if (!exactKeys(command, ['cmd', 'identityId'])) return reject('browser_command_keys_invalid');
      if (command.identityId !== TARGET_ID) return reject('identity_not_fresh_or_confirmed');
      if (!['idle', 'aborted', 'complete'].includes(state.activeView.control.phase)) {
        return reject('active_view_session_active');
      }
      stage = 0;
      state = initialState();
      state.activeView.reports = [reportFor(stage)];
      state.activeView.control = {
        ...emptyControl(),
        phase: 'waiting_operator_confirmation',
        sessionId: SESSION_ID,
        identityId: TARGET_ID,
        proposalId: COARSE_PROPOSAL_ID,
        reasons: [],
        evidenceIdsShort: ['sha256:aaaaaaaaaaaa…', 'sha256:bbbbbbbbbbbb…'],
        moveReady: true,
        kind: 'coarse_pose',
        targetPoseId: 'demo_table_center',
        maxStepM: 0.02,
      };
      notify();
      return { accepted: true, action: 'start', sessionId: SESSION_ID };
    }

    function confirm(command) {
      if (!exactKeys(command, ['cmd', 'sessionId', 'proposalId'])) {
        return reject('browser_command_keys_invalid');
      }
      const control = state.activeView.control;
      if (control.phase !== 'waiting_operator_confirmation' || control.moveReady !== true) {
        return reject('confirmation_not_expected');
      }
      if (command.sessionId !== control.sessionId) return reject('session_id_mismatch');
      if (command.proposalId !== control.proposalId) return reject('proposal_id_mismatch');
      stage += 1;
      state.sequences = {
        lumos: state.sequences.lumos + 1,
        d435: state.sequences.d435 + 1,
      };
      state.activeView.reports = [reportFor(stage)];
      if (stage === 1) {
        state.activeView.control = {
          ...control,
          proposalId: REFINE_PROPOSAL_ID,
          kind: 'refine_delta',
          targetPoseId: 'demo_refine_left_15mm',
          maxStepM: 0.015,
          moveReady: true,
        };
      } else {
        state.targets[0].positionM = [0.342, -0.118, 0.041];
        state.activeView.control = {
          ...control,
          phase: 'grasp_preview',
          proposalId: null,
          reasons: ['simulation_only', 'physical_grasp_not_authorized'],
          kind: null,
          targetPoseId: null,
          maxStepM: null,
          moveReady: false,
        };
      }
      notify();
      return { accepted: true, action: 'confirm', sessionId: SESSION_ID };
    }

    function cancel(command) {
      if (!exactKeys(command, ['cmd', 'sessionId'])) return reject('browser_command_keys_invalid');
      if (command.sessionId !== state.activeView.control.sessionId) return reject('session_id_mismatch');
      if (['idle', 'aborted', 'complete'].includes(state.activeView.control.phase)) {
        return reject('session_not_active');
      }
      state.activeView.control = {
        ...state.activeView.control,
        phase: 'aborted',
        proposalId: null,
        reasons: ['operator_cancelled'],
        moveReady: false,
      };
      notify();
      return { accepted: true, action: 'cancel', sessionId: SESSION_ID };
    }

    function send(command) {
      if (!command || typeof command !== 'object' || Array.isArray(command)) {
        return reject('browser_command_invalid');
      }
      if (command.cmd === 'start_active_view') return start(command);
      if (command.cmd === 'confirm_active_view_step') return confirm(command);
      if (command.cmd === 'cancel_active_view') return cancel(command);
      return reject('browser_command_unsupported');
    }

    function subscribe(listener) {
      if (typeof listener !== 'function') throw new TypeError('listener must be a function');
      listeners.add(listener);
      return () => listeners.delete(listener);
    }

    return Object.freeze({ snapshot, send, subscribe, cameraPanels });
  }

  return Object.freeze({ createActiveViewDemo });
}));
