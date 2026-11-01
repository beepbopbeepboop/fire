# GATE: `make check` job `doc-refs` is red

## Status (2026-11-01, OPEN)

`make check` (the user's run) reports `doc-refs` failed in 4 s. The ratchet names two files that cite a deleted
document more than `tools/dangling_refs_baseline.py` allows:

```
ratchet: 2 file(s) cite MORE deleted docs than tools/dangling_refs_baseline.py allows:
  formal/arm64_proof_gen.py: 3 (baseline 0) — FORMAL_integer_overflow_at_run_time_is_still_untrapped.md
  test_formal_call_proof_gen.py: 3 (baseline 0) — FORMAL_integer_overflow_at_run_time_is_still_untrapped.md
```

Cause: the 2026-10-31 move of `bugs/FORMAL_*.md` to `bugs/formal/` (commit `21d3363c5`) rewrote most path citations but
missed these. Each of the citations still says `bugs/FORMAL_integer_overflow_at_run_time_is_still_untrapped.md`, a path
that no longer exists. The document itself is at `bugs/formal/FORMAL_integer_overflow_at_run_time_is_still_untrapped.md`.

## Fix (planning done; the change is mechanical)

1. Find every citation with `grep -n 'bugs/FORMAL_integer_overflow' formal/arm64_proof_gen.py test_formal_call_proof_gen.py`
   and rewrite each to `bugs/formal/FORMAL_integer_overflow`. Lines that already read `bugs/formal/` do not match the grep.
   Some citations wrap across two lines; the second line of a wrapped citation carries no `bugs/` prefix, so check those by hand.
2. Do not touch `tools/dangling_refs_baseline.py`. The ceiling for these files stays at 0.
3. Run `python3 tools/dangling_doc_refs.py --ratchet`; it must pass with no ceiling change.

## Quick test

`python3 tools/dangling_doc_refs.py --ratchet` exits 0. Then this doc is deleted in the same commit as the fix.
