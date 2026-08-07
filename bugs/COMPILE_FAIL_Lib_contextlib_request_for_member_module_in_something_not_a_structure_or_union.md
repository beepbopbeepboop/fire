# COMPILE_FAIL: Lib/contextlib.py — request for member '__module__' in something not a structure or union

## Status (updated 2026-08-06)

Re-ran with a 150s timeout: TIMED OUT again (no output at all before
the timeout, not even the usual `drop stale export` dylib-link noise
that normally appears seconds in). Retried standalone with a longer
background run — still running after 9+ minutes before being killed
for this session's time budget, on a machine also running several
other agents' `mojo.py build` processes concurrently (this session is
one of many parallel worktree-agent-* sessions).

This matches the ALREADY-DOCUMENTED performance hard bug
`bugs/hard/PERF_nested_module_compile_walk_ast_quadratic_rescan.md`
almost exactly — that doc's own confirmed repro is THIS EXACT FILE
(`Lib/contextlib.py`, chosen specifically because it imports `abc`,
`collections`, `functools`, `os`, `sys`, `types`, `warnings`, ...): a
`cProfile` run there shows `_walk_ast` called 4.47 MILLION times for
just 36 nested `gen_module` invocations, a confirmed quadratic-ish
blowup in the transitive-import compile path (do_imports=True) — not
a timing fluke or system load artifact, a real algorithmic issue with
a concrete root cause and phased fix plan already written up in that
doc.

The ORIGINAL `__module__`/"consolidated" note below is STALE (from an
older bug-tracking scheme predating the current `bugs/hard/` layout;
the referenced `consolidated/` directory no longer exists) — not
re-verified since the file doesn't get far enough to reach a GCC error
at all anymore, it never finishes compiling within any reasonable
timeout. Not investigated further here beyond confirming the PERF
hard-bug match — see that doc for the real fix plan.

## Original stale note (pre-2026-08-06, unverified)

**TIMEOUT resolved** (2026-07-25) — the hang was caused by the multi-name
`import a, b, c` binding bug (fixed in commit 52ea4d7). The file no longer
times out, but now hits COMPILE_FAIL errors in its transitive dependencies.

```
request for member '__module__' in something not a structure or union
```

This error pattern was tracked in:
`consolidated/COMPILE_FAIL_cc_error_request_for_member_x_in_something_not_a_structure_o.md`
(directory no longer exists as of 2026-08-06).

Source file: `/Users/mrs/net/Python-3.14.6/Lib/contextlib.py`
