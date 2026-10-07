# TEST: `test_transitive_closure_capture.py` is `expect=` for a reason that no longer exists — it fails on a FILENAME the 2026-09-26 rename deleted

## Status (2026-09-30 — OPEN, one-line fix, filed by the fix-round8-selfhost worker)

`tools/suite.py` registers this test as a known failure:

```python
test('transitive-closure-capture', [PY, 'test_transitive_closure_capture.py'],
     deps=['preflight'],
     expect='closure capture through a transitive import — behaviour gap',
     desc='closure capture through a transitive import — behaviour gap')
```

The reason is not the one the marker gives. The test does not reach the
capture logic at all: it dies in the harness, compiling a runtime source
that has not existed under that name since commit `563ec43a`
("Rename compiler and runtime sources to fire") renamed
`runtime/mojo_async_runtime.cpp` to `runtime/fire_async_runtime.cpp`.

## What was run, and what it saw

```
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_transitive_closure_capture.py
memcap: t -- ceiling 8.0 GB across the process tree
FAIL  test_bare_create_task_from_sibling_closure  exception: g++ compile of
      mojo_async_runtime.cpp failed: cc1plus: fatal error:
      /Users/mrs/net/chatgpt/claude/work-48/runtime/mojo_async_runtime.cpp:
      No such file or directory
      compilation terminated.

FAIL  test_taskgroup_10000_stress_from_sibling_closure  exception: (same)

Results: 0 passed, 2 failed
```

`ls runtime/mojo_async_runtime*` → no such file. `git log -1 --
runtime/mojo_async_runtime.cpp` → `563ec43a`, whose stat shows
`{mojo_async_runtime.cpp => fire_async_runtime.cpp}`.

Both cases are async (`create_task` from a sibling closure, a TaskGroup
stress run), so the test needs the async runtime compiled with g++ — which
is what the stale path name is asking for.

## Why this is worth a row rather than a shrug

CLAUDE.md's rule on `expect=` is that a marker is a silenced test, and a
stale one is worse than no marker because it reports green while covering
nothing. This one is exactly that case: the marker's reason ("behaviour
gap") and the actual failure (a compile of a deleted file) are different
bugs, so the marker is hiding a harness regression AND whatever the real
behaviour gap is — two unknowns behind one "EXPECTED". The suite's tally
counts this as a test that ran.

Note the neighbouring registration in the same file is the same shape:
`test('...', ..., expect='async capture of a mutable binding — behaviour
gap, not registered before this')` — worth checking whether it has the same
stale-path problem, since it is one grep away.

## Exact next step

1. In `test_transitive_closure_capture.py`, replace the
   `mojo_async_runtime.cpp` path with `fire_async_runtime.cpp` (grep the
   file; the harness builds the async sources by name).
2. Re-run. Whatever it prints then is the REAL state of the test: either it
   passes, in which case drop the `expect=` marker from `tools/suite.py`
   (the runner reports a marked-but-passing test as a failure, so this
   forces the decision), or it fails on the capture itself, in which case
   re-file the behaviour gap with the actual symptom — which is a bug this
   doc cannot state, because nothing has run the test since the rename.

Verify the same two steps for the `async mutable capture` registration
directly above it in the same `tools/suite.py` block.
