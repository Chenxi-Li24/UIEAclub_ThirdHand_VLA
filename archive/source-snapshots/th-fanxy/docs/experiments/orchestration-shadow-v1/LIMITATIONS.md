# Limitations

The benchmark is replay/shadow evidence, not a real-robot experiment. It measures orchestration
advancement decisions on ten synthetic scenario families; it does not measure grasp quality,
trajectory safety, perception generalization, household-task success, or hardware reliability.

`always_model` and `hybrid` use deterministic scripted accounting in v1. Their latency and cost are
configured constants, not measurements from an online model. The unsafe baselines are pure
evaluators and are intentionally unable to dispatch commands.

No autonomous physical-performance claim is supported until separately reviewed real trials are
performed. This delivery structurally fixes `robot_execution_enabled=false` and
`can_execute_world=false`.
