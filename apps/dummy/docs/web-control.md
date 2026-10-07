# Dummy Web Control

## UI and Ownership

The right-hand drawer contains a collapsed **Dummy** section with start, stop,
keyword subscription, measured J1/J4 angles and an optional recognition preview.
Opening a page never starts Dummy. Start opens a physical-motion confirmation.
J1/J4 follow has a 50 degrees/s J1 cap. Keywords can drive all joints through the
existing gesture scheduler. Idle breathing and automatic Home remain disabled.

Web Service owns only the child it starts, using a fixed Python entry point and
`shell:false`. It does not create an SDK or open a camera. Dummy connects through
TouchR1Adapter to the existing 3000 Robot Service and consumes shared Vision data.
The local telemetry includes PID and checkout identity. An external terminal-run
Dummy is displayed read-only and must be exited before web-managed start.

Stop sends SIGTERM only to the owned Dummy. Its normal cleanup stops follow,
closes detection, keyword subscription, telemetry and Robot websocket. It does
not disable motors or stop shared Robot/Vision/Speech. Status remains `stopping`
until process exit; a failed exit is not reported as successful. A keyword waypoint
already in progress may need its bounded completion wait (default 45 seconds).
Web shutdown waits up to 60 seconds for cleanup and never forces a shared service
shutdown. Software stop is not an independent hardware emergency stop.

Closing or refreshing the browser does not stop a web-managed Dummy. Use **Stop
Dummy** before leaving the operating station. Reopening the page reads the same
server-owned process state. Stop the web service gracefully, not with SIGKILL.

## Routes

All routes are same-origin and return JSON with `Cache-Control: no-store`:

- GET `/api/dummy/status`: process phase, ownership, readiness, observation and
  actual backend speed caps. No command is sent to the robot.
- POST `/api/dummy/start`: exactly `{"authorized":true,"keywords":true}`.
  Requires fresh (500 ms) connected/ready Robot feedback, idle Robot, upgraded
  50 degrees/s backend, ready Vision, and prepared Python/URDF/face model.
- POST `/api/dummy/stop`: exactly `{}`. Idempotent for the managed process.
- GET `/api/dummy/frame`: an atomic same-source JPEG/observation JSON packet,
  only for the child owned by this web process.

Mutation requests require JSON and reject cross-origin browser requests. They
accept no executable, path, shell argument or target joint supplied by the browser.
This is not user authentication: keep existing LAN/tailnet access restrictions.

Status is polled without overlap once per second. Preview fetches at most 4 Hz
and only while enabled, visible, expanded and running. Hiding the panel, scrolling
it out of view, switching browser tabs or stopping Dummy cancels the request and
clears the image. It opens no additional camera stream or detector. Green boxes
are fresh locks, yellow circles the controller's filtered 2D target, white crosses
the image center; held candidates use orange/gray.

## Resources and Deployment

By default resources resolve inside the checkout. Web launch can explicitly set
`DUMMY_RESOURCE_ROOT` to an existing prepared checkout; this does not modify it.
Specific overrides: `DUMMY_PYTHON`, `DUMMY_URDF_PATH`, `DUMMY_FACE_MODEL`,
`DUMMY_YOLO_MODEL`, `DUMMY_SPEECH_WS`, `DUMMY_TELEMETRY_PORT` (default 31024,
must not be zero). Web passes `VISION_HTTP_URL` into Dummy as
`DUMMY_VISION_HTTP_URL`. Speech transcript subscription derives from
`VOICE_WS_URL` with path `/v1/transcripts` unless overridden.

Logs append to `runtime/logs/dummy-web.log` in the web checkout. No conda activation
is required when the explicit prepared Python is used. Never run a second physical
Robot Service: stop follow, support the arm and obtain on-site approval before
restarting the sole SDK for this backend update.

## Manual Verification

Default tracking now uses a face-only target. See [face-follow.md](face-follow.md)
for startup selection, automatic reacquisition and the not-yet-connected OK switch.

1. Reload the test web page, expand Dummy. It must remain stopped without motion.
2. With an old backend, start stays disabled and an upgrade reason appears.
3. After a supervised backend upgrade, check reported J1/J4 caps and live Robot
   readiness. Cancel the start dialog: no process or motion should start.
4. At a safe test pose, first uncheck keywords and confirm start. Watch measured
   angles and same-source recognition while making small movements.
5. Hide the preview/panel or browser tab: frame requests should stop in the browser
   Network panel; status is read-only and the existing follow continues.
6. Stop Dummy and wait for stopped. Robot remains connected; ordinary web controls
   must work afterward. Repeat with keyword subscription only after this passes.
7. Increasing the cap does not guarantee reaching 50 degrees/s: proportional
   error, acceleration, SDK smoothing and geometry still constrain actual speed.
