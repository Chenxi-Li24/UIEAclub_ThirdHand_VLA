# Three-step local control workspace

## Bottom conversation panel

The composer is now a viewport-centered bottom overlay attached directly to the workspace root. Opening Natural language does not change the current route. Navigation among overview, model, vision, calibration and system pages retains the conversation, draft and recording state. The lower-left entry toggles visibility; closing remains blocked during active/starting recording. Existing calibration navigation guards still apply to page changes. Reply windows remain anchored above the composer. Validation: 22 shell/English-interface tests pass; browser checks confirm horizontal centering, persistent drafts across four pages, and close/reopen without route changes.

Natural language remains in the lower-left navigation. The bottom-right composer is a single rounded input with a reply toggle, send button and right-hand microphone icon. It has no heading, description, footer or Text/Voice tabs. Replies and action confirmations appear in a separate floating window above the input; users can close and reopen it without losing drafts. New messages or candidates reopen the reply window. The microphone icon opens compact voice controls without acquiring a microphone or starting recording automatically. Audio settings remain in a details section. Voice controls cannot be closed while recording starts or runs. Existing execution confirmation and recording navigation guards remain intact. Validation: 21 shell/English-interface tests pass. Browser inspection confirms a 76-pixel-high composer, hidden headings, independent reply dismissal and English-only visible text. Hardware speech/control was not exercised.

## English-only interface

All shipped HTML pages now contain English initial labels, tooltips and accessibility text. Chinese language controls are removed. The translation layer always selects English, and legacy guest/account language preferences normalize to English. Camera diagnostics and TCP calibration include English static and dynamic copy. Existing translation catalogs remain as compatibility mappings for legacy controller messages; user-provided command content and backend payloads are not rewritten. A source scan of HTML and a rendered workspace text/attribute scan verify that no Chinese interface text is present in the checked states. External/user content is not covered by that guarantee.

The default local workspace opens System ready, followed by Natural language and Digital twin. Existing voice candidates, preview, reject/confirm, manual controls, history and waypoints retain their controllers. The sidebar mirrors the existing connection, SDK, robot and AI status elements, including unavailable states.

## Preparation

GET /api/system-ready returns availability, pending, overall, CAN and per-service results. POST starts asynchronous preparation and requires a loopback peer, localhost Host, same Origin and X-ThirdHand-Action: prepare on Linux. Duplicate requests and active robot/grasp/depth/teaching operations are rejected. No caller-supplied command or profile is accepted.

The fixed manual-control profile is loaded by apps/web/src/system-ready.js. It reuses CanInterfaceManager and ServiceSupervisor.ensureAll, excluding the already-running web gateway. CAN failure stops preparation. Full-profile CAN recovery is refused with host_recovery_required; use ./thirdhand ensure --profile manual-control on the host for that case. The operation does not connect, enable, home or command the arm. Preparation results are in-memory, reset on gateway restart, and describe the last attempt, not perpetual service health.

The browser polls every three seconds, disables unsupported/duplicate actions, and lists actual service results. An unavailable API is never rendered ready. The web gateway must already be running to serve the button. On a cold host use the existing launcher command first. No new database, dependencies or environment variables are required; existing runtime assets, sudo CAN permissions and configuration are still required.

## Cloud boundary

Cloud assets include the new stylesheet. Existing access checks and model-only navigation remain authoritative; restricted assistant shortcuts are omitted. Cloud startup is not proxied into a local privileged launcher: preparation is explicitly unavailable remotely. Cloud admin motion and database integration require separate deployment validation.

## Validation

Node 24: 21 targeted shell/preparation tests pass. Full Web suite: 437/450 pass; failures include missing local SDK configuration and Windows directory fsync EPERM. Cloud startup/entry tests: 3/4 pass; the remaining integration test requires TEST_DATABASE_URL. Chrome inspection of static frontend confirmed default overview, ordered feature entries, sidebar offline feedback, unavailable preparation, and no horizontal overflow. Static preview does not validate robot geometry delivery or hardware. No physical movement or deployment was performed.

## One-click system check

The overview now provides Run system check and Run again. Six rows inspect the gateway API, fresh SDK feedback, AI service port, vision service port, host network interfaces, and Ubuntu Wi-Fi. Progress advances only after each result, with an animated active-row indicator and reduced-motion support. Failures do not stop remaining checks; duplicate runs are ignored. Completion shows an issue count and time. Existing global chat remains available across pages.

GET /api/system-diagnostics?check=sdk|ai|vision|network|wifi returns {id,status,detail,checkedAt}. SDK uses existing robot state freshness. Service probes have a three-second timeout and do not perform inference or motion. Network checks address assignment, not internet reachability. Wi-Fi reads fixed nmcli TYPE,STATE fields with a three-second timeout; no adapter is skipped, disconnected Wi-Fi is a warning, unavailable inspection is unknown. No SSID or credentials are collected. Browser requests time out after eight seconds. This read-only endpoint works over Tailscale; existing localhost-only preparation remains unchanged. Missing services can be started with the command under Service setup. No new dependencies, database changes or configuration are required. Restart the web gateway after installing the new server module; frontend assets use the existing static server.

Validation: 28 focused Node tests pass, including stale SDK rejection, Wi-Fi result distinctions, failure continuation, progress completion, duplicate-run suppression, and retry. Physical motion and AI inference are not part of self-check acceptance.
