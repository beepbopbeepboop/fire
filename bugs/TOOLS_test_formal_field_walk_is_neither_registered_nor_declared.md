# suite-self-test is red: `test_formal_field_walk.py` is neither registered nor declared

**Area:** TOOLS (the registry estate). NOT `work/gatefix6`'s — filed by a
worker whose subject was two other gate failures, which it hit and did not fix.

## What I ran

    python3 tools/suite.py formal-sweep-truth arm64-encoders suite-self-test --no-cache

    suite: 3 passed, 1 failed
    FAIL  suite-self-test  (46s)  exit 1
    ...
    FAIL  the estate: every test file is run by something, or says why not:
          not run by any registered spec and not in UNREGISTERED:
          test_formal_field_walk.py

The full text of the failing row is in `build/suite.log` under `suite-self-test`.

## What it is

`test_formal_field_walk.py` arrived with the `formal19-1`/`formal19-2` merges
(`git log --oneline -- test_formal_field_walk.py` → `c1310813`, `078ecbed`). No
spec in `tools/suite.py` runs it and `test_suite.py`'s `UNREGISTERED` does not
declare it, which is the one hole that check exists to close — so `check` is red
on a file that is not in `check`.

It is a real suite, not a scratch harness: it pins
`formal/model.py::iter_statement_nodes` against the full walk over the shapes
that made the first version wrong (a nested class inside a method, an `except`
arm, a `match` arm), with `tools/formal_field_walk_differential.py` as the
measurement behind it. So this is a coverage hole and not a stale entry, which
is the distinction `test_suite.py` draws between the two fixes.

## Why it is not mine

Two claims touch it and neither is `tools:gatefix6`: the file is
`formal19-1`'s / `formal19-2`'s, and the registry entry belongs with the file
that needs it. Registering it inside a fix for two unrelated gate failures would
also put a cost decision (a new gate job) into a branch nobody is gating.

## Next step

One line, in whichever way the file's owner prefers:

* **register it**, if it is meant to run every gate —
  `test('formal-field-walk', [PY, 'test_formal_field_walk.py'], ...)` beside the
  other `formal-*` rows, with a measured cost and memclass. It builds no image
  and runs no Lean (it is a walk over `.py`/`.mojo` sources), so the
  measurement to take is the wall time and the peak of one run; or
* **declare it**, if it is a tool-adjacent suite the owner does not want in
  `check` — an `UNREGISTERED` entry in `test_suite.py` naming the reason, which
  is what that table is for and what the check reads.

Re-verify with `python3 tools/suite.py suite-self-test --no-cache`, which must
reach `ok` and say so.