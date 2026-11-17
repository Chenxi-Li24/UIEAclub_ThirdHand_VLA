# Administrator workspace repair

## Requirements

Administrator chat must use the current compact workspace interface and English UI/replies. An explicit AI model preview must update the same Digital Twin, joint/gripper inputs and simulation state used by the authenticated workspace. A pending model must not block ordinary conversation or be replaced with an invented home pose. Guest behavior remains supported through the shared presenter/provider.

Cloud and Guest Calibration pages must clearly report that local hardware calibration is unavailable and permit ordinary navigation. Real local calibration continues to block leaving during unknown initial status or active/pending teaching; no timeout or missing callback counts as proof of a safe physical state.

Investigate public SDK connectivity through the existing authenticated cloud/relay/local robot chain. SDK connection itself can enable motors and move the configured gripper: do not issue a live connect, disconnect, stop, lease takeover or motion command during diagnosis. Actual runtime conclusions require authorized server access; source inspection and anonymous HTTP results are not hardware verification.

## Constraints

- Node.js 24; no new runtime dependency or database migration.
- UI and AI reply text are English. User names, entered messages and raw device reason codes remain literal.
- Authenticated AI uses existing session, Origin, CSRF and `voice.use` authorization (Administrator mode plus MFA).
- Chat has no robot command, lease, SDK, microphone, camera or private-history tool.
- Model-only previews retain the explicit `Preview in model` action. Do not claim physical execution.
- Preview joints are six finite absolute degrees within the actual model limits; gripper is null or finite in [0,1]. Validate the whole proposal before changing anything, including gripper zero.
- Use the current model context, preserving unrelated joints. Missing/out-of-edit-range joint context is null, never clamped or replaced with home.
- An AI model edit pauses live following; later telemetry cannot overwrite it until the user explicitly resumes Sync.
- Preserve account layouts, role restrictions, read-only device policy, real confirmation/lease checks and local teaching/recording navigation guards.
- No secrets, database contents or runtime output in Git. Use new immutable public release assets when deployment is possible.

## Planned modules and interfaces

`services/cloud-api/src/ai-preview.js` exports `createAiPreviewService({fetchImpl,env,now})`, returning `{chat(body,clientKey)}`. It shares bounded provider/schema/quota handling with the existing Guest HTTP adapter. The provider remains the existing configured service and accepts no execution tools.

`services/cloud-api/src/routes/ai-preview.js` exports `aiPreviewRoute(context)`. Only POST `/api/v1/ai/preview` is handled; the main server applies session/Origin/CSRF checks before this route, and the route checks `voice.use` before calling `context.previewAi.chat(body,clientKey)`.

`apps/web/public/js/ai-preview-chat.js` exports `mountAiPreviewChat({document,view,shell,request})` as CommonJS and `ThirdHandAiPreviewChat`. It returns `{bindModel(adapterOrNull),dispose()}`. The request callback takes the bounded chat body and returns `{reply,joints,gripper,mode:'preview-only'}`. A model adapter is `{read(),limits,apply(result)}`; read returns the actual model joints/gripper, and apply validates before updating simulation. The presenter knows no privileged transport.

Authenticated startup supplies session-backed transport and binds the adapter only after model geometry is ready. Guest supplies its existing public transport and actual model adapter. Existing IDs remain usable; legacy voice candidate/execution placeholders are hidden by the new presenter.

`workspace-shell.js` treats an authenticated bootstrap or Guest marker as unavailable local calibration by default. Explicit local wizard configuration keeps its original guard. This protects against premature/default shell mounts without removing an existing unsafe iframe.

## Verification and delivery

Record focused tests, local UI verification, public deployment and physical validation separately. The known starting full Node baseline is 574/592 with 18 existing failures; compare current failures rather than weakening checks. Server SSH authentication is currently unavailable, so public SDK diagnosis and rollout remain pending until access succeeds.

## Shared AI preview components (Task 1 implemented)

The shared libraries are available independently of startup wiring:

- `services/cloud-api/src/ai-preview.js` exports `createAiPreviewService({fetchImpl,env,now})` with asynchronous `chat(body,clientKey)`. Bodies contain a nonempty message up to 2000 characters, up to eight user/assistant history entries (2000 characters each), `joints` as six valid absolute model degrees or explicit `null`, and optional `gripper` as null or a finite value in [0,1]. User content remains literal; provider history is reduced to role/content fields. No execution tools are supplied.
- The provider uses the existing `GUEST_AI_API_KEY`, optional `GUEST_AI_MODEL` (default `deepseek-flash`), and existing DeepSeek Anthropic-compatible endpoint. Each instance limits concurrency to three, total requests to 120/hour, requests per client to 10/minute and active client buckets to 2048. Requests have a 30-second provider deadline. Replies contain only `{reply,joints,gripper,mode:'preview-only'}`; failures carry sanitized `code` and `status` (400 invalid input, 429 busy, 503 unavailable). English is requested in the provider prompt and non-Latin letters are rejected; this is not semantic language detection for languages using Latin script.
- Null current joint context does not invent a home pose. Conversation and gripper-only proposals remain available, but provider responses proposing joints without current joint context are rejected. Joint context outside the actual adapter limits is sent as null, without clamping. Complete preview proposals are checked again against actual model limits before application.
- `guest-ai.js` keeps its existing HTTP signature and supports optional `{service}` alongside `{fetchImpl,env,now}`. It keeps exact path/method/Origin checks, loopback-only trusted `X-Real-IP` handling, the existing unconfigured-provider response and sanitized errors. Integration must supply the same service instance used by authenticated chat so quotas are shared; Guest uses client IP and authenticated chat uses user ID.
- `routes/ai-preview.js` exports `aiPreviewRoute(context)` and handles the exact `/api/v1/ai/preview` path. `POST` checks `voice.use` (Administrator role/mode and MFA) before invoking `context.previewAi.chat(body,principal.userId)`. Authorized wrong methods return 405 with `Allow: POST`; other paths pass through. This route relies on the server's session, Origin, CSRF and bounded JSON body middleware and does not replace them.
- `apps/web/public/js/ai-preview-chat.js` exports `mountAiPreviewChat({document,view,shell,request})` through CommonJS and `ThirdHandAiPreviewChat`. `request(body)` supplies the transport and returns the bounded result; the presenter contains no transport URLs. The returned `{bindModel(adapterOrNull),dispose()}` permits chat before geometry readiness. The adapter is `{read:()=>({joints,gripper}),limits,apply(result)}`. `apply` must itself validate the complete result and synchronously update the same model, inputs and simulation state atomically; return `false` to reject. Gripper zero is valid, and null joints leave unrelated joints unchanged.
- Previews require an explicit `Preview in model` click. A missing adapter offers a retry; successful application dispatches `thirdhand:model-preview` and navigates to Control. A successful reply dispatches `thirdhand:ai-reply`. Eight request-history entries and 40 displayed message rows bound browser history. Duplicate submissions are ignored; disposal removes submit/keyboard listeners, blocks retained preview actions and ignores late replies. Legacy interpretation/execution candidates and voice setup placeholders are hidden; Software Stop and SDK controls remain intact.

No dependency, schema/database, model resource or configuration-file change is required. Existing startup commands and model-asset restore procedures remain unchanged. Task 1 alone does not mount the presenter or publish the authenticated route: startup/session/server/Guest integration must supply the shared service, authenticated request callback and actual model adapter after geometry readiness. Authenticated preview application must pause live following and update simulation; only explicit Sync may resume telemetry following.

Validation: `node --test tests/node/public_access/ai-preview.test.js tests/node/public_access/ai-preview-route.test.js tests/node/public_access/ai-preview-chat.test.js tests/node/public_access/guest-ai.test.js` passes 24/24. Presenter checks use the actual `index.html` DOM through LinkeDOM. This verifies standalone provider/HTTP adapters, authorization and DOM behavior; full middleware, integrated simulation, browser layout, real provider, public deployment and physical hardware are separate evidence and remain unverified by Task 1. No provider or hardware request was made.

## Calibration capability and navigation (Task 2 implemented)

`mountWorkspace(document, view, options)` resolves the calibration capability once, before the initial hash route can create an iframe. An omitted `calibrationEntry` defaults to `null` when the trusted `workspace-bootstrap` element or `app.dataset.guestDemo === 'true'` is present. Explicit `null` also disables the local wizard. The Calibration page then displays English unavailable-local-hardware guidance, creates no iframe, and permits ordinary page navigation and opening chat. This covers a premature default cloud shell mount before authenticated startup supplies its own options.

Plain local mounts still default to `tcp-calibration.html?embedded=1`; an explicitly configured wizard retains its URL and safety guard. Loading or unknown initial feedback blocks leaving, active/pending teaching keeps its unsafe latch, and confirmed idle feedback releases it. Presentation timeouts, missing callbacks and later disconnected snapshots do not clear an unsafe latch. Repeated mounts return the existing shell and never remove an existing unsafe iframe. Recording/open-chat guards remain unchanged. The shell and Guest navigation checks issue no robot commands.

Only `apps/web/public/js/workspace-shell.js` changes runtime behavior; the mount API, startup commands, configuration files, resources and database remain unchanged. No dependency or asset restore step is added. Validation: `node --test --test-force-exit --test-timeout=25000 tests/node/web/workspace-shell.test.js tests/node/public_access/guest-workspace.test.js` passes 33/33, including real index DOM and Guest initialization, cloud pre-mount, local/custom wizard, persistent teaching and recording cases. Full-suite comparison and integrated browser checks belong to final integration.

The reproduced source bug is conditional: a default mount under the cloud marker could create a wizard before the explicit unavailable mount. The existing explicit-null authenticated source path is safe; current staging Guest Calibration was also observed to leave successfully for Digital Twin before this fix. These observations do not reproduce or verify the deployed Administrator session. Authenticated deployment, real wizard/service feedback and physical hardware behavior remain separate validation work; this task makes no hardware or SDK request.
