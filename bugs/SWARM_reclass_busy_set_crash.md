# SWARM_reclass_busy_set_crash: the reclass pass crashes every pass (`unhashable type: 'dict'`)

**Status:** FIXED 2026-11-10 (regression test, traceback, and the stale-code root cause). The defect
itself was already fixed on `master` by commit `e2aca65eb` (2026-11-10 01:49:22).

STOP: fixed — the busy set holds task names (e2aca65eb); the repetition was a stale swarm process, now caught by `swarm.stale_code()` which re-execs when tools/*.py changes. Pinned by `tools/test_swarm_reclass_busy_set.py`.

## What I saw

`.git/control/swarm.out` — 157 identical failures, one per pass, from the first pass after the swarm
started until the present:

    18:50:38 reclass failed: TypeError("cannot use 'dict' as a set element (unhashable type: 'dict')")
    18:55:33 reclass failed: TypeError("cannot use 'dict' as a set element (unhashable type: 'dict')")
    ...
    08:53:15 reclass failed: TypeError("cannot use 'dict' as a set element (unhashable type: 'dict')")

`python3 tools/swarm.py --who`:

    LOCK HELD ... {"pid": 68947, "ppid": 47051, "started": "2026-11-09T18:46:05", ... "argv": ["tools/swarm.py"]}
    live process: 68947 ... Python tools/swarm.py
    command is tools/swarm.py: yes

## Root cause (two layers)

1. **The defect (fixed at `e2aca65eb`).** `apply_moves` built its "who is busy" set from task
   *dicts*:

       busy = {t for t in C.load().values() if C.state_of(t) == "running"}      # dicts -> unhashable
       busy_bases = {c[4:] for t in busy for c in t.get("claims", []) ...}

   A set cannot hold a dict, so the comprehension raised before any move was attempted. The fix
   builds the set from task **names** (`C.load().items()`). Verified: with the current file,
   `apply_moves(load_state())` runs to completion and moves the pending doc
   (`reclass: moved bugs/SUITE_silentnoop.md -> bugs/mid/SUITE_silentnoop.md`).

2. **Why it never stopped (fixed here).** The swarm is a long-lived process. It read
   `tools/swarm.py` once at start (2026-11-09 18:46:05); the fix landed at 01:49:22 the next morning.
   Every later pass re-ran the old in-memory `apply_moves` and crashed again. Nothing in the swarm
   noticed that its own code changed, so a landed `tools/` fix took effect only when a human
   restarted it — and until then the log looked exactly like "the fix did not work".
   `swarm.stale_code()` now hashes `tools/*.py` at start and re-execs the swarm at a pass boundary
   when the hash changes (the lock fd is closed first, so the new image can take the lock).

## Consequence

While that process runs, no doc ever changes class: the reclass move is the thing that carries a
doc from `bugs/` to `bugs/mid/` / `bugs/hard/`, so an escalated doc stays in its old class and the
next worker is queued in the wrong class (the failure mode `61495cc2f` and `061dc9410` describe).
`swarm.json`'s `pending` map is never drained.

## Fix

- [x] `busy` holds names, not task dicts (`e2aca65eb`).
- [x] Regression test pinning it (`tools/test_swarm_reclass_busy_set.py`): a running worker no longer
      breaks the move, a doc a live worker holds is still not moved, and `stale_code()` re-execs on a
      changed `tools/*.py`.
- [x] Log the traceback, not `%r` of the exception: `reclass failed: TypeError(...)` named the
      exception but not the line, which is why this took a manual `git show` to attribute.
- [x] The swarm reloads its own code (`stale_code()`).
- [x] Dropped the now-dead `busy` name set in `apply_moves` (it was overwritten on the next line).

## Repro

    grep -c "reclass failed" .git/control/swarm.out          # 157
    python3 tools/swarm.py --who                              # pid 68947, started 2026-11-09T18:46:05
    git show e2aca65eb -- tools/swarm.py                      # the code fix
    python3 tools/test_swarm_reclass_busy_set.py              # the pin
