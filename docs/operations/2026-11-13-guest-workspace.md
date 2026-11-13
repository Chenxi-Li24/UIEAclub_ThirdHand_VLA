# Guest workspace and public camera — 2026-11-13

The login page links to `/guest#control`. Guests can orbit/zoom the hosted robot, adjust six model joints and gripper position, load Home/Inspection/Pick preparation poses, save and recall browser-local waypoints, and export the current visit's demo history. All workspace navigation remains accessible. Robot connection, motion, grasping and calibration collection actions open a **Control permission required** dialog. They do not call control endpoints. Real run history and account data still require sign-in. AI text conversation and model previews are available as described below; guest voice transcription remains unavailable.

At the user's request, camera viewing is now public at `/guest#vision`. It is a read-only raw-image preview refreshed every two seconds, not low-latency operator video. The existing authenticated LiveKit pipeline and robot readiness policies are unchanged. A dedicated Ubuntu publisher reads only `http://127.0.0.1:3100/camera/xvisio/raw` and uploads JPEG frames to the cloud. It never calls robot endpoints. Guest viewing stops while the page is hidden or another workspace is selected. No image history is stored.

## Modules and APIs

- `services/cloud-api/src/guest-pages.js`: public shell, bounded asset allowlist, final import-map CSP hash, camera route dispatch.
- `services/cloud-api/src/guest-camera.js`: exact `/guest-camera/frame` endpoint. GET/HEAD are public. POST requires a dedicated publisher bearer token, JPEG content type, valid JPEG boundaries and at most 1 MiB. The last frame lives in process memory and expires eight seconds after receipt. Missing/stale frames return 503, and the browser hides the old image. Other methods return 405. Restart clears the image. This endpoint does not expose device lists, telemetry, logs or accounts.
- `apps/web/public/js/guest-workspace.js`: local previews/storage/history, permission dialog and public-camera viewer.
- `tools/guest-camera-publisher.py`: Python standard-library publisher, two-second upload interval, bounded frame buffer, reconnects after source/network errors. Logs contain no credentials or images.

No database schema changes or dependencies. Existing `/api/v1/` authentication remains unchanged. Preview timestamps represent cloud receipt, not certified sensor capture time; this channel must not be used for motion safety/readiness.

## Configuration and deployment

Cloud: `GUEST_CAMERA_UPLOAD_TOKEN` in root-only `/etc/thirdhand-stage/guest-camera.env`, loaded by `thirdhand-stage.service.d/guest-camera.conf`. Nginx proxies only the exact `/guest-camera/frame` path to the existing business upstream, with a 1 MiB body limit. Disable uploads by removing that environment configuration and restarting the cloud service. Do not put tokens in Git or frontend code.

Ubuntu: publisher installed at `~/.local/lib/thirdhand/guest-camera-publisher.py`; mode-0600 `~/.config/thirdhand/guest-camera.env` contains `GUEST_CAMERA_UPLOAD_URL` (HTTPS frame endpoint) and the matching `GUEST_CAMERA_UPLOAD_TOKEN`. User service `thirdhand-guest-camera.service` runs Python 3 with that environment file, Restart=always, RestartSec=5, NoNewPrivileges=true. Start with `systemctl --user enable --now thirdhand-guest-camera.service`. It requires the existing vision service on port 3100. It does not start, connect or enable the robot. Stop with `systemctl --user disable --now thirdhand-guest-camera.service`.

Cloud release: `/opt/thirdhand-stage/releases/guest-camera-20261113`; previous `/opt/thirdhand-stage/releases/guest-20261113`. Nginx backup: `/var/backups/thirdhand/nginx-before-guest-camera-20261113.conf`. Rollback stops the publisher, restores Nginx, restores the previous `current` symlink, removes the guest-camera environment drop-in and restarts the cloud service. Keep the prior authenticated camera configuration intact.

## Validation and limits

Run `node --test tests/node/public_access/guest-workspace.test.js tests/node/public_access/guest-camera.test.js`: tests cover anonymous asset/API boundaries, CSP, guest navigation/control permission dialog, authenticated-only frame uploads, oversized/invalid image rejection, public image access and stale-frame expiry. Python publisher passes syntax compilation. The physical robot is not moved during testing.

Browser-local demo data is not a real robot run. Camera preview availability depends on the Ubuntu source and outbound network. Formal phone/WeChat testing, a feedback form, single-CTA main landing-page changes and guest voice transcription are separate remaining work.

Public browser verification: an isolated, logged-out session displayed a 640-pixel-wide real camera image; switching to Digital Twin stopped frame requests (count remained 23), and returning to Vision resumed viewing. Clicking Send opened the permission dialog without a control request. Anonymous devices and real history returned 401; unauthorized camera POST returned 403. The visible guest page contained no Chinese text and no console errors. The Ubuntu user publisher service was active.

## Public AI Agent — 2026-11-13

Guest AI now uses a real server-side DeepSeek `deepseek-flash` call through the provider's Anthropic-compatible Messages API. The same authorized provider credential already used by the Ubuntu speech deployment is copied over SSH into a root-only cloud environment file; it is never returned to the browser or committed. `services/cloud-api/src/guest-ai.js` handles exact POST `/guest-ai/chat`, requires the configured same-origin Origin header, JSON input up to 16 KiB, messages up to 2,000 characters, eight recent conversation turns and a valid six-joint model pose. The request has no tools, no camera image, no private history and no robot endpoint. The upstream URL is fixed. Provider protocol reference: https://api-docs.deepseek.com/guides/anthropic_api/.

Responses contain English text, an optional validated six-joint model pose and optional gripper preview. Joint bounds match the bundled model: J1 [-162,162], J2 [-12,201], J3 [-183,0], J4/J5 [-98,98], J6 [-164,164]. The browser requires a separate Preview in model click to apply a candidate. Request robot access only opens the existing permission dialog. No AI response is interpreted as code or HTML. A 30-second provider timeout, three-request concurrency ceiling, ten requests per minute per trusted client address, and 120 requests per hour globally limit public usage; counters reset on service restart. Errors show a retry message without provider secrets. Conversation context is kept in tab memory and sent to the provider; no database persistence or new dependencies.

Cloud configuration: `/etc/thirdhand-stage/guest-ai.env` (0600) contains `GUEST_AI_API_KEY` and `GUEST_AI_MODEL=deepseek-flash`; `thirdhand-stage.service.d/guest-ai.conf` loads it. Nginx routes only `/guest-ai/chat`, with a 16 KiB body limit. Release `/opt/thirdhand-stage/releases/guest-ai-20261113` preserves the previous camera release; Nginx backup `/var/backups/thirdhand/nginx-before-guest-ai-20261113.conf`. Rollback restores that backup and previous release symlink, removes the AI environment drop-in, reloads Nginx and restarts the cloud API. Existing camera uploader and authenticated robot services remain unchanged.

The chat retains the bottom-center composer, closeable reply window and cross-workspace behavior. Enter sends; Shift+Enter adds a line. Guest voice transcription is not connected yet and explicitly prompts for typed input. AI does not inspect the public camera. Browser validation with a logged-out session received a real English response for J1=20 degrees; applying its preview updated only J1 and the permission button opened the control-access dialog. Automated guest AI/camera/workspace tests cover origin denial, invalid roles and inputs, output bounds, request quota, anonymous private API denial and camera freshness.
