# Ground-truth labeling

Ground truth is stored in each checked scenario fixture independently of runtime decisions. Each
step-attempt has three labels: local effect, semantic handoff readiness, and final task goal. Labels
are tri-state (`PASS`, `FAIL`, `UNKNOWN`).

An advancement is false if its corresponding truth is `FAIL`, `UNKNOWN`, or missing. Intermediate
advancement requires both effect and handoff truth to pass. Terminal completion requires both
effect and task-goal truth to pass. This deliberately treats missing truth as unsafe.

Synthetic fixtures encode observation identity, depth validity, robot holding state, region state,
receipt status, and ordered evidence snapshots. They do not contain private live-camera images.
