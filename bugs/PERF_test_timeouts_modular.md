# PERF: 70 test timeouts

## Symptom
70 modular test files time out during compilation (>120s). Likely heavy integration tests (linking, offload, large modules).

## Notes
- Tooling: tools/run_modular_suite.py now runs the full suite with a 10-minute (600s) per-test timeout (configurable via --timeout).
- Remaining work: profile the 70 slow tests and optimize, or move them to a slow bucket.
EOF