# Primary Project Omission Supplement: 2026-10-08

## Scope And Locations

This supplement applies only to the isolated integration worktree:
`/home/nieqingcao/ThirdHand/worktrees/deployment-to-main-20261007`.
The live source remains `/home/nieqingcao/ThirdHand/UIEAclub_ThirdHand_VLA`.
No live source edit, service restart, camera acquisition, SDK construction,
robot movement, integration commit or push is part of this supplement.

The saved deployment snapshot is `727aa2c`. The primary subsequently advanced
through `e1c0e9b`, `179fec2` and `522cd2b`. Their effective source changes are now
merged or adapted in the integration index, but their Git ancestry is not yet
merged. See `latest-deployment-inventory-20261008.json` for all 14 paths.

## Filled Source Omissions

- The fixed-TCP application is at `apps/fixed_tcp_demo`. Its command-line client
  requests the existing Robot Service on port 3000, instead of constructing a
  second SDK owner. The default request is non-executing; real execution requires
  both `--execute` and `--no-dry-run`. It does not connect or enable a robot itself.
- Robot Controller, WebSocket server and Python bridge include the fixed-TCP
  command, capability, correlated status and existing-owner adapter. The bridge
  imports the relocated app. Continuous follow commands and owner cleanup remain
  present; the formal Dummy source, configuration and tests retain the mainline
  baseline unchanged.
- The webpage retains the `go around` button after preset-grid rebuilding.
  Its admission and active-request state follow Robot Service feedback. A click
  is a real motion request when execution is permitted, not an offline preview.
- The obsolete direct-SDK `arm.py` is preserved under
  `History/fixed-tcp-before-port3000`, not loaded from the active application.
- All three newly added primary tests are present, and formal CI wrappers cover
  the CLI, bridge, controller and webpage contracts using fake transports/arms.
- Stop propagation prevents a cancelled demo from issuing a later return-to-zero
  command. The bridge preserves global `DRY_RUN` even if a client asks to execute.
- Each motion run has irreversible cancellation and a connection generation;
  reconnect is refused until the unfinished worker exits. Every fixed-TCP stage
  uses the ordinary service's bounded speed scale, including lower settings.
- Demo cancellation requires both the admitted socket owner and request ID.
  Rejected duplicate IDs do not gain ownership. Cancelled queued commands receive
  correlated terminal errors. Proxy request records are finalized on confirmed
  stop; transport loss instead retains an uncertainty interlock until fresh
  authoritative idle feedback or a confirmed stop, without assuming physical idle.
- A legacy experimental tracker now rejects a repeated camera frame rather than
  issuing a held target with a new timestamp. Its deterministic regression test
  preserves the original stale-frame assertion. Formal Dummy was not changed.

## Historical Calibration Materials

All 30 non-cache files from the original `local/calibration/source` are preserved
byte-for-byte at `History/legacy-calibration-20261008/source`. The sibling
`source-manifest.json` records original SHA-256, sizes and per-file disposition.
The 27 source/text/JSON files are staged for historical traceability.
The original handover Markdown's double-space line breaks are byte-preserved;
one file-specific Git whitespace attribute permits those original hard breaks.

Three payloads remain local-only and ignored: the captured NPZ sample, historical
YOLO PT weights and historical ONNX file. The ONNX is zero bytes in the original;
it is an archived artifact, not a usable model. Their manifest entries are staged,
not the payloads. No historical calibration is silently approved, normalized or
loaded as current XVisio evidence. Do not run archived scripts: some contain
camera/SDK construction and real motion operations.

Ordinary logs, backups, `.orig` files, Apple metadata and the accidental filename
remain untouched in the primary. Runtime environments and caches are not source
omissions and are not committed.

## Offline Verification

The supplement's verification used a temporary Python 3.11 environment and fake
hardware/network interfaces, not a newly installed production environment:

- Node: 243 passed.
- Formal Python: 263 passed, plus 58 passed subtests.
- Formal Dummy: 224 passed.
- Archived experimental Dummy: 119 passed.
- Boundary audit: ready.
- Runtime resource verify-only: 4097 size/SHA-256 checks, zero assembled files.
- Inventories: 147 saved snapshot files and 85 direct dependencies accounted for.
- Supplement: 14 latest-primary paths accounted for; 30 historical file hashes
  match the original.

See `INTEGRATION_REVIEW_20261007.md` for reviewer findings and limitations.
These results do not certify physical calibration, stopping, collision clearance,
browser rendering, model quality, autonomous grasping or deployment readiness.

## Still Not Finished

- The integration tree's Python/vision environments and XVisio executable have
  not been prepared. Do not claim that this worktree can already start all services.
- Complete bottle-grasp 3D trajectory-preview routing, non-lift-only `buildPlan`
  injection and the optional `WEB_GRASP_CONFIG` implementation are not complete.
- Four confidence-runtime API/UI contracts remain explicitly documented under
  `tests/pending/vision`; their original evidence is preserved, not represented as
  passing functionality.
- Old SDK-frame policy bindings require separate revalidation against the final
  SDK/configuration. GRIP candidate evidence is not a physical approval.
- Meituan motion remains disabled by the approved source-only migration scope;
  cross-client route ownership must be adapted before later motion enablement.
- The existing indirect fast-uri moderate advisory remains disclosed; no
  unrelated automatic package upgrade was performed.

## Next Git Steps

1. Obtain approval to save the current pending integration merge commit. It
   preserves the mainline baseline and deployment snapshot `727aa2c` as parents.
   No push or live directory switch is included in that approval.
2. Perform an ordinary merge of the deployment branch through `522cd2b` into the
   integration branch. This preserves the three later commits as ancestry, even
   though their source is already adapted. Resolve any rename/delete/add conflict
   per module, rerun offline checks, and ask before saving the next merge commit.
   Do not replace `MERGE_HEAD`, rebase, squash, cherry-pick or force-push.
3. Fetch and ordinarily merge any newer fork main changes; review and rerun tests.
   Obtain approval to push the integration branch and create the fork-main PR.
   Require GitHub CI and approval before using Merge Commit on that PR.
4. Open the updated fork-main PR against Chenxi-Li24 main. Check its differences
   and CI, obtain approval, and use Merge Commit. Do not push upstream main directly.
5. Prepare the final runtime and plan a separate deployment switch. Only after
   service-stop/hardware-watch confirmation may the primary switch to main and
   fast-forward from the merged upstream main. Do not automatically resume motion.
6. Verify all valid deployment work and ancestry are contained in main and no
   worktree uses the obsolete deployment branch, then request cleanup approval.
   Delete branches normally, not forcibly to hide omissions.

## Later Runtime Preparation

Do not copy or commit an old Conda/virtualenv tree. After the Git integration is
saved, prepare a controlled, non-live deployment directory with Linux x86_64,
Python 3.11, Node.js 24, Git LFS and network/package access. The existing script is:

```bash
bash tools/assets/setup_clone.sh
```

It restores manifest resources, installs system/packages (including the packaged
XVSDK), creates isolated Python/Dummy environments, installs Node dependencies
and builds Startouch bindings and the XVisio executable. This changes machine
packages and needs separate installation approval; it was not run here. Ubuntu
22.04 package availability and XVSDK compatibility must be verified, not assumed.
High ASR has an optional backend and compatible CUDA/GPU requirements; inspect
`--with-high-asr` before selecting it. The script itself does not start services.

After preparation, verify resources and required binaries/configuration without
constructing the SDK. Use the existing launcher only after separate deployment
approval; program startup and real motion remain separate authorization steps.
