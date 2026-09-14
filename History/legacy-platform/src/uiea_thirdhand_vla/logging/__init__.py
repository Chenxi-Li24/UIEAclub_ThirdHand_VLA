"""
Logging module  structured per-run data recording.

Each run produces a timestamped directory under logs/:
  logs/YYYY-MM-DD_HH-MM-SS_taskname/
    run_log.csv           Structured event log
    state_transitions.jsonl  FSM transition trace
    frames/               Timestamped image captures
    metadata.yaml         Config snapshot + git commit
"""
