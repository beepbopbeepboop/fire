# PERF: 70 test timeouts

## Symptom
70 modular test files time out during compilation (>120s). Likely heavy integration tests (linking, offload, large modules).

## Notes
- Need to profile and optimize, or increase timeout. Consider running these in a separate slow bucket.
EOF