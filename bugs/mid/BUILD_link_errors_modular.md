# BUILD: 24 link errors (collect2: ld returned 1 exit status)

## Symptom
24 modular test files fail at link stage with "collect2: error: ld returned 1 exit status".

## Affected files
See failures_detail.txt for the full list (grep "collect2").

## Notes
- Need to investigate root cause (missing symbols, ABI mismatch, etc.).
EOF