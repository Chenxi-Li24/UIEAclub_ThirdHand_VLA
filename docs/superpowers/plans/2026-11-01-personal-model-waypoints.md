# Personal Model Waypoints Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans task-by-task. Preserve existing dirty/staged identity work; no Git commit/push. Final independent review, one RED→GREEN fix pass.

后续用户授权（2026-11-01）：阶段完成后更新详细说明、跟踪必要新文件、按功能提交并普通推送fork origin/login；以后每个完成且通过必要检查的独立功能自动本地提交。此新授权取代上面原始“不提交/推送”约束，其他任务内容与历史仍须保留。

**Goal:** Save an account's current model pose and recall it after signing in again.
**Architecture:** Reuse simulation.user_programs, authenticated same-origin endpoints and a model-only panel. Server owns account/source/model version; model playback never imports device transport.
**Tech Stack:** Existing Node/CommonJS, browser JS, PostgreSQL, Node tests.
**Spec:** ../specs/2026-11-01-personal-model-waypoints-design.md

## Global Constraints
- Model only; 6 finite numeric degrees and gripper0..1; known model limits; name1–120; max100/account.
- Account-bound durable server storage; English default and existing Chinese switch.
- Preserve latest identity/camera/readonly device changes; no hardware commands or new dependencies.
- New deployment permissions reviewed separately after local implementation, not applied as a side effect of tests.

## Review Focus
- Another user's UUID must never reveal/delete their item.
- Concurrent creates cannot exceed100; failed save cannot appear successful.
- Late requests and stopped/replaced playback cannot revive a disposed model panel.
- Malformed stored data/model mismatch must not mutate the model.
- Model unavailable/playing and live language change must keep controls/status accurate.

### Task1: Account storage and API
Files: new platform/storage/src/model-waypoints.js, services/cloud-api/src/routes/waypoints.js; server route registration; tests/node/public_access/model-waypoints.test.js.
- [x] RED tests for durable two-session read, isolation/deletion, strict shape/numerics, max100 race and request auth/CSRF.
- [x] Implement fixed model contract and principal-scoped SQL, route using existing simulation.use.
- [x] GREEN against isolated PostgreSQL and loopbackHTTP; no production DB.

### Task2: Model playback and panel
Files: simulation-controller.js; new model-waypoints.js browser panel/CSS; cloud-workspace.js/workspace-pages.js; component-scoped bilingual copy; tests/node/public_access/model-waypoints-ui.test.js and model-waypoint-playback.test.js.
- [x] RED six-axis+gripper interpolation/stop, invalid input/no mutation, save/load/recall/delete/error/bilingual and readiness/dispose races.
- [x] Implement optional gripper in simulation steps, panel using sessionClient and simulation only, wire after geometry ready and dispose on pagehide.
- [x] GREEN targeted and related workspace/simulation tests.

### Task3: Reviewable delivery
- [x] Related complete local regression with isolated PG; independent final review then one RED→GREEN fix pass if needed.
- [x] Prepare exact latest-baseline source delta and least-privilege simulation schema/table grant SQL; no server apply before concrete review.
- [x] Update handoff/status with implemented vs deployed evidence, retain original physical motion/video blockers.

### Task4: Approved C6 staging deployment
- [x] Receive exact source/grant approval; upload and hash-check3 fixed artifacts; readonly review then apply exits0.
- [x] Full4634-file/current/protected-config/readonly-health/anonymous401 and actual PostgreSQL persistence verification.
- [x] Real owner save/refresh/admin recall, same-account Observer recall; retain clearly named model test point.
- [x] Real owner logout/new Observer login reread and recall, user entered credentials; J1 10→0 completed. Long spinner later completed; cause remains unconfirmed and recorded separately.
