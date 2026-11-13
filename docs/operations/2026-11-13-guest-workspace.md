# Guest workspace and public camera — 2026-11-13

The login page links to `/guest#control`. Guests can orbit/zoom the hosted robot, adjust six model joints and gripper position, load Home/Inspection/Pick preparation poses, save and recall browser-local waypoints, and export the current visit's demo history. All workspace navigation remains accessible. Robot connection, motion, grasping and calibration collection actions open a **Control permission required** dialog. They do not call control endpoints. Real run history and account data still require sign-in. AI/voice are explicitly marked unavailable until a public demo AI service is configured; no simulated reply is represented as a model response.

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

Browser-local demo data is not a real robot run. Camera preview availability depends on the Ubuntu source and outbound network. Formal phone/WeChat testing, a feedback form, single-CTA main landing-page changes and a connected guest AI service are separate remaining work.

Public browser verification: an isolated, logged-out session displayed a 640-pixel-wide real camera image; switching to Digital Twin stopped frame requests (count remained 23), and returning to Vision resumed viewing. Clicking Send opened the permission dialog without a control request. Anonymous devices and real history returned 401; unauthorized camera POST returned 403. The visible guest page contained no Chinese text and no console errors. The Ubuntu user publisher service was active.
