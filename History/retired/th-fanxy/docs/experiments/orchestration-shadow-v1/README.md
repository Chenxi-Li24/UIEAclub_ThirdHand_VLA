# Orchestration Shadow Benchmark v1

This checked experiment evaluates the paper claim that effect verification plus semantic handoff
verification reduces false task advancement under bounded recovery. It runs ten deterministic
Pick/Place replay scenarios against five baselines and never opens a camera, network connection,
robot SDK, CAN interface, or actuator path.

The five references are `receipt_only`, `rule_only`, `post_action`, `always_model`, and the proposed
`hybrid`. The first and third are deliberately unsafe counterexample simulators; they receive no
executor object. Model latency and cost are configured accounting constants. No model service is
called.

Reproduce from the repository root:

```bash
.venv/bin/python scripts/orchestration/run_benchmark.py \
  --manifest configs/orchestration/benchmark_v1.yaml \
  --skills configs/skills/tabletop_pick.yaml configs/skills/tabletop_place.yaml \
  --output-dir artifacts/orchestration-shadow-v1 \
  --baseline receipt_only --baseline rule_only --baseline post_action \
  --baseline always_model --baseline hybrid
```

Primary paper outputs are `table.md`, `table.tex`, `metrics.json`, `summary.csv`, and the failure
gallery. Every result declares `robot_execution_enabled=false`.
