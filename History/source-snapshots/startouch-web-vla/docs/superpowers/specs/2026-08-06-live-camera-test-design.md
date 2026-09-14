# Live Camera Test Page Design

Date: 2026-08-06

## Goal

Make the normal camera-test page an unambiguous real-camera test: opening it must show
the live Lumos wide-angle stream and live D435 stream without depending on the online
vision-overlay pipeline. Keep the synthetic active-view demo separate and visibly
labelled.

## Selected approach

The normal page at `/camera-test.html` is live-first:

- Lumos initially uses the same-origin raw stream `/camera_lumos`;
- D435 initially uses the same-origin stream `/camera`;
- both camera panels are visible together above the fold on a desktop viewport;
- the page continues to read `/api/vision/status` and connect `/ws` for read-only status
  and the existing ID-only active-view protocol;
- the page never enables robot or gripper execution.

The synthetic workflow remains available only through the explicit `?demo=1` URL. Its
persistent simulation banner, local SVG panels, zero-network transport, and execution
locks remain unchanged.

## Optional Lumos overlay

The Lumos panel exposes an explicit “algorithm overlay” control rather than making the
overlay the default. Selecting it probes `/camera_lumos_vision` for a first image frame
with a bounded timeout. The visible raw stream is replaced only after the probe succeeds.
On error or timeout, the raw stream remains visible and the page reports that the overlay
is unavailable. Returning to raw mode is immediate.

Demo mode hides/disables this live-only overlay control and creates no probe.

## Layout

On screens wider than 900 px, Lumos and D435 appear side by side in a two-column camera
grid. Each feed uses a 16:9 box so image content begins near the top of the page instead
of being vertically centred below an oversized blank region. On narrower screens the
feeds stack in one column.

## Failure behavior

- A missing raw stream uses the existing bounded retry behavior and labels that camera
  unavailable; failure of one camera does not hide the other.
- A stalled overlay never replaces the raw Lumos image.
- Vision-status errors and calibration blockers remain visible but do not suppress raw
  camera display.
- The page never falls back from real mode into synthetic data.

## Verification

Tests must prove:

- normal mode declares `/camera_lumos` and `/camera` as its default streams;
- demo mode makes no raw, overlay, API, or WebSocket request;
- a stalled overlay keeps the raw Lumos stream visible;
- a working overlay can be selected and switched back to raw;
- both live camera rectangles intersect the first desktop viewport;
- real local endpoints deliver bytes for both cameras;
- existing ID-only commands, safety locks, demo state machine, proxy, and browser tests
  remain green.

## Non-goals

- repairing the depth-provenance failure in the old online inference process;
- claiming that calibration, depth accuracy, observation paths, or grasping are valid;
- enabling active-view motion, robot motion, or gripper commands.
