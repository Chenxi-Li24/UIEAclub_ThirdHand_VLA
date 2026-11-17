# Administrator Workspace Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Repair authenticated English chat/model synchronization and calibration navigation, and establish the real public SDK connection failure without moving hardware.

**Architecture:** Share a bounded model-only AI service/presenter between Guest and authenticated startup. Keep real execution in the existing separately authorized SDK control chain. Make cloud calibration capability explicit before any iframe can be created; preserve real local teaching protection.

**Tech Stack:** Node.js 24, vanilla JavaScript, existing PostgreSQL identity contracts, linkedom/node:test; no new dependency.

**Spec:** `docs/features/ADMIN_WORKSPACE.md`

## Global Constraints

- UI and AI reply text are English; preserve literal user content and raw device reason codes.
- Authenticated AI uses existing session, Origin, CSRF and `voice.use` authorization (Administrator mode plus MFA).
- Chat has no robot command, lease, SDK, microphone, camera or private-history tool.
- Preview joints are six finite absolute degrees within actual model limits; gripper is null or finite in [0,1]. Validate all fields before mutation.
- Missing/out-of-edit-range joint context is null, never clamped or replaced with home.
- AI edits pause live following until explicit Sync resume.
- Preserve account layouts, role restrictions, read-only device policy, confirmation/lease checks and local teaching/recording guards.
- No new dependency/database migration. No real credentials or runtime outputs in Git.
- Diagnose SDK read-only; never issue live connect/disconnect/stop/takeover/motion during this work.

## Review Focus

1. Chat during delayed/failed model loading: useful English replies, no invented pose or unbound mutation (Tasks 1/3).
2. Invalid six-joint data, partial vectors, NaN and gripper zero: atomic rejection or exact application (Tasks 1/3).
3. Measured joints outside editing limits: preserve measured display and reject joint drafts without clamping; gripper-only preview remains independent (Tasks 1/3).
4. Default/repeated cloud shell mounts: no local iframe trap; unknown or active real wizard never bypassed (Task 2).
5. Anonymous/Observer/stale-MFA/cross-origin/bad-CSRF requests and late disposed callbacks: deny appropriately without leaking privileged data or control transport (Tasks 1/3).

### Task 1: Shared bounded AI service and compact presenter

**Files:** Create `services/cloud-api/src/ai-preview.js`, `services/cloud-api/src/routes/ai-preview.js`, `apps/web/public/js/ai-preview-chat.js`; modify `services/cloud-api/src/guest-ai.js`; create focused AI service/route/presenter tests under `tests/node/public_access/`. Do not edit startup, session, server, workspace-pages, guest-pages or guest-workspace wiring in this task.

**Interfaces:** Follow the exact factories, callback/adapter shapes and route in the Spec. `createGuestAi` additionally accepts optional `{service}` while preserving its existing `{fetchImpl,env,now}` API. `chat(body,clientKey)` returns the bounded result and throws errors with `code` plus HTTP `status`; the Guest wrapper and authenticated route return the documented status without exposing provider exceptions. Client quota keys are guest IP or authenticated user ID; callers share one service instance during integration.

- [ ] Add failing tests for existing Guest compatibility, valid/invalid/null context, English reply validation, timeout/quota and no execution tools; implement provider extraction with original limits (3 concurrent, 120/hour total, 10/minute/client, 2048 active client buckets).
- [ ] Add failing route tests for Administrator+MFA versus anonymous/Observer/no-MFA and exact route/method. Implement route authorization; full HTTP middleware coverage belongs to Task 3.
- [ ] Add failing real-DOM presenter tests for delayed model, exact joint/gripper preview, invalid proposal atomicity, duplicate submissions, English messages, bounded history and ignoring late replies after disposal. Implement presenter and preview adapter binding; no network path is hardcoded in the presenter.
- [ ] Preserve `Preview in model`, support gripper-only zero, and hide obsolete voice interpretation/execution placeholders without removing Software Stop or SDK controls. No hardcoded fallback home pose.
- [ ] Run focused tests, update the feature doc with implemented contracts/validation, self-review, and commit only task-owned files. Report exact commands/results and remaining integration needs.

### Task 2: Calibration capability and navigation recovery

**Files:** Modify `apps/web/public/js/workspace-shell.js`, `tests/node/web/workspace-shell.test.js`, `tests/node/public_access/guest-workspace.test.js`; update the calibration section of the feature doc. Do not edit authenticated startup or its tests in this task.

**Interfaces:** `mountWorkspace(document,view,options)` retains its API. When `calibrationEntry` is omitted and a `workspace-bootstrap` element or `app.dataset.guestDemo==='true'` exists, default the effective entry to null before navigation creates a frame. An explicit null is unavailable. Plain local default/custom wizard retains current behavior. Do not clear an existing unsafe iframe on a repeated mount.

- [ ] Reproduce a default cloud pre-mount entering Calibration before authenticated mount; assert no iframe can be created under the trusted cloud marker and all ordinary routes remain reachable. Implement narrow capability defaulting.
- [ ] Add Guest initialization navigation regressions and explicit English unavailable-calibration copy. Preserve all real wizard loading/active/pending/unknown latch and recording tests.
- [ ] Test local default mount still blocks leaving an unknown/unsafe wizard and confirmed idle releases it; no timeout escape and no command requests.
- [ ] Run focused checks, document behavior and current-source versus deployed uncertainty, self-review, and commit only task-owned files.

### Task 3: Authenticated integration, English first render and SDK diagnosis

**Files:** Modify `apps/web/public/js/workspace-startup.js`, `workspace-session.js`, `guest-workspace.js`; `services/cloud-api/src/server.js`, `guest-pages.js`, `workspace-pages.js`, `workspace-bootstrap.js`; focused startup/model/bootstrap/HTTP/Guest tests and feature docs.

**Interfaces:** Server `createCloudApi` accepts optional `previewAi` for tests; otherwise creates one shared service and Guest handler. Pass `previewAi` into authenticated route context and optional Guest AI handler into `serveGuestPage`. Authenticated chat transport calls `/api/v1/ai/preview` through session.request with a 35-second client timeout; provider timeout remains 30 seconds. Session.request accepts an optional third argument `{timeoutMs}` without changing existing requests. Bind chat to `controls.simulation` and the exact current model after ready; validate full joint/gripper proposals before applying either.

- [ ] First add failing authenticated-startup/model tests: admin chat enabled before geometry, preview binds afterward, exact inputs follow it, new live samples do not overwrite the AI draft, explicit Sync resumes. Observer AI remains unauthorized. Preserve measured out-of-edit-limit display.
- [ ] Wire shared presenter into Guest and authenticated startup, remove only the authenticated Administrator chat toggle from legacy disabled lists, keep old physical/voice channels disabled, and dispose callbacks during page exit. Keep Guest permission behavior and public assets allowlist/CSP.
- [ ] Add HTTP integration tests for sessions, Origin, CSRF and `voice.use`; share the provider quota instance between public/authenticated routes. Test no legacy proxy routes/tools are opened.
- [ ] Normalize initial authenticated HTML/bootstrap UI locale to English without modifying account database rows or user content; add old-locale regression coverage.
- [ ] Inspect SDK catalog/client/config paths and public endpoints without connecting hardware. If SSH becomes available, read active release, service state, relay/SDK diagnostics and existing operation activity before any deployment. Otherwise record the precise access limitation and leave the runtime claim unverified.
- [ ] Run focused suites, boundary/whitespace checks and appropriate full Node comparison; request independent review. Record accepted residual baseline failures accurately.
- [ ] Commit the integrated change and documentation. If server access and authorization permit, deploy a finite reviewed immutable release delta with rollback and fresh versioned assets, then verify actual signed-in UI. Never substitute source/tests/Guest success for authenticated or hardware success.
