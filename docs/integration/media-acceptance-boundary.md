# Media implementation and acceptance boundary

The B6 adapter uses pinned official SDKs: Node server2.19.2, browser2.23.0 and
Python RTC1.2.0; Pillow13.0.0 decodes bounded local JPEGs. Python3.11 compatibility
was checked against package metadata. Node24 is required. CI runs this transport
environment separately from the legacy ML environment.

## Authorization and privacy

Both human roles receive video-subscribe-only tokens. No browser grant can publish
video, microphone, data or manage rooms. Tokens stay in tab memory. Device camera
publication uses a different camera-only identity/token, obtained through mTLS,
Ed25519 proof over exact request bytes and the current device connection context.
It never grants a Robot control lease or calls SDK connect.

Self-hosted LiveKit removal does not invalidate an old token by itself, and JWT
expiry does not disconnect an already connected viewer. See the official
[token lifecycle/revocation documentation](https://docs.livekit.io/frontends/reference/tokens-grants/#token-revocation).
Consequently, these adapters require all signalling/rejoin requests to pass the
same-origin session gate. Private SFU signalling/API ports must have no public
bypass. Session logout/disable/expiry removes the viewer and rejects cached or
refreshed tokens at that gate.

Ruling: if the trusted SFU removal request fails, stop renewing publication leases
for that device until removal is confirmed. The device independently expires its
signed publication lease within950ms and stops submitting new frames even if the
grant request or source is blocked. This can interrupt other viewers too; it
prefers a privacy hold to an indefinitely authorized former viewer. Cached frames
already delivered cannot be recalled. The actual encoder/network buffering delay
and failure cutoff still require B6/C2 measurement; mocks are not proof of a
deployed privacy bound.

## Source, timing and control

One private Vision Service stream feeds one publisher; the SFU fans it out to
viewers. `/edge-media/v1/raw` is literal-loopback, credential protected, rejects
Cookie/Origin and accepts at most one publication subscriber. It reuses the camera
already owned by Vision Service. Public Nginx must not forward this endpoint.

The current native camera supplies a host **receipt** monotonic timestamp and
sequence, not a verified sensor exposure timestamp. The existing MJPEG stream
only includes sequence. Receipt/decode time is not renamed capture time. Missing
capture timing remains unavailable and allows viewing only. It cannot satisfy
remote-motion readiness. C3 must integrate sensor timing or a measured bounded
capture-latency/clock profile before this check can pass.

When reliable/bounded capture metadata exists, it travels on the video frame as
user timestamp plus frame ID. The browser correlates rendered frames with that
metadata and submits IDs, not a `cameraReady` boolean. Cloud validates them against
the authenticated publisher's recent source frames. This is a consistency check,
not cryptographic proof of human attention or an unmodified browser. Independent
source freshness and the local execution gate remain authoritative.

The Robot Service independently verifies the signed publication report, exact
boot/executor/connection/certificate, a monotonic deadline, a newly advancing frame
and bounded capture age. Repeating an old frame cannot refresh local freshness.
Recording, hardware acceptance and a verified initial stopped baseline are also
required. A changed worker/config invalidates that baseline. Default hardware and
initial-stop callbacks are false; incoming JSON/environment flags do not enable
them. Simulation tests bypass physical acceptance explicitly.

## Actual status

- Policy/HTTP/mTLS suites pass locally with actual JWT validation, test
  certificates and isolated sessions. Local source authorization and its existing
  Vision regressions pass with FakeCamera. Python publisher tests use FakeRTC and
  synthetic frames, including blocked renewal/source and monotonic expiry.
- The browser camera panel is explicit and subscribe-only. The main cloud entry
  now has an explicit opt-in camera-only composition; controlService remains
  absent. The currently deployed staging release enables camera-only composition.
- Actual Ubuntu testing on2026-10-31 passed real XVisio→LiveKit1.13.11→RTC
  decode:8frames640×480, advancing IDs; repeated successfully after the user
  moved the camera USB port. Both runs used loopback listeners only, no SDK,
  no recording, and cleaned up temporary processes. Capture time is still
  unverified. This is not proof of cloud authentication or WAN performance.
- The pinned browser SDK defaults to `/rtc/v1`; the same-origin gate now
  explicitly handles new and old signal/validation paths. Origin remains
  mandatory for viewer WebSockets; only diagnostic validation accepts absent
  Origin with trusted proxy-supplied same-origin Fetch Metadata. Actual HTTP
  tests cover wrong origin/site/path, duplicate tokens and post-logout denial.
- The reviewed same-origin Nginx gate, private SFU/API and camera-only Linux
  services are deployed. Real Administrator browser video and two simultaneous
  subscribers render640x480; both human roles separately pass real HTTPS grant
  and signaling authorization. The two actual browser subscribers used the same
  Administrator session. Cached-token rejoin after synthetic logout is rejected.
  A separate real-account logout cleared both connected SFU subscribers while
  preserving the publisher; the monitor window includes pre-click waiting and
  does not establish a precise logout latency or decoder privacy deadline.
- Persistent verified mTLS and signing after the cold handshake fix observed
  lease/grant failures without widening the950ms/50ms publication gate. Edge
  regressions33/33 and business regressions131/131 pass. Short stable observation
  does not establish long-duration network or privacy bounds.
- Still required: measured encoder/network/decoder cutoff, long-duration/load and separate
  UDP-only/TCP-only path evidence, any needed TURN/TLS fallback, production
  rotation and ten-viewer measurement. A35-second private SFU-management fault
  was initially rejected; the user then explicitly approved it. Three initial
  C2g attempts auto-cleared their exact rule and recovered publication.
  Attempt2 correlates a browser close with HTTP503 and track removal, but the
  harness10-second synchronization assertion failed. The other attempts mix in
  existing disconnections; none of those initial attempts passed. Original
  reports are retained, and subsequent C2i acceptance is recorded separately.
- Staging limits viewing to2sessions on the existing3Mbps cloud link, with no
  resource purchase. See the [C2g actual record](../operations/2026-10-31-C2g-camera-change.md).
- Voice typed proposal/confirmation adapters and the full existing administrator
  action set remain pending. Bare voice/vision/Dummy/control proxies stay closed.
- No default video/audio recording, source-history deletion or resource purchase
  has been added. Production/hardware acceptance is not claimed.
- C2i subsequently coalesces each small signed HTTP report into one TLS write
  after real TCP metadata identified split-header retransmission delays.35edge
  tests and5Ubuntu TLS tests pass; a five-minute zero-viewer baseline has no
  failures. Leases/read deadlines are unchanged. After owner reauthentication,
  two actual Observer browser videos decoded640x480;300.018seconds/61samples
  passed, followed by the strictly synchronized35second removal-failure retest,
  independent cleanup and actual post-recovery viewing. One post-fix natural
  timeout before this viewing window is retained; long-term stability and the
  encoder/network/decoder deadline remain unaccepted. Public SDK remains off.
