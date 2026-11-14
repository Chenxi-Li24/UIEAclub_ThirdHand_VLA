# Explicit TCP policy relocation

The deployed measured TCP remains bound to its original frame policy. A
repository merge or SDK asset hydration is not a new physical calibration.

The existing code-only rebind still requires identical immutable evidence
paths. For byte-identical geometry copied to new paths, the web grasp loader
also accepts an explicit `thirdhand-tcp-policy-relocation-v1` certificate:

- `source_policy_id` and `runtime_policy_id` bind the exact policy bytes.
- `aliases` maps every original non-code binding to a current bound file.
- Source/destination basenames and SHA-256 contents must match, with unique
  source and destination paths and complete coverage.
- The SDK configuration must map to the configuration actually used by the
  runtime policy. Tool transform and source semantics cannot change.
- Both policies still validate every bound file, including additional SDK
  evidence. Conflicting copies of an original geometry file are rejected.

Configure the deployment-only grasp JSON with `tcpSourceFramePolicyFile`,
`tcpSourceFramePolicyId`, `tcpPolicyRebindingFile`, and
`tcpPolicyRebindingId`. The last ID is the SHA-256 of the certificate bytes.
No relocation is inferred without this explicitly hash-bound record.

Keep the shared runtime policy, hand-eye matrices, TCP candidate, validation
report and active manifest unchanged. Only restart the web gateway after
confirming no active grasp, depth acquisition, teaching or other robot
control. Do not restart the robot/vision services or change speed as part of
this repair. Numerical compatibility is not physical path/grasp approval.

Before cutover, back up the two changed web modules and deployment grasp
configuration. Verify the active TCP ID/transform and shared artifact hashes
before and after restart. On failure, restore those exact backup files and
restart only the web gateway again.
