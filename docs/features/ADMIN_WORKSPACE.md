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
