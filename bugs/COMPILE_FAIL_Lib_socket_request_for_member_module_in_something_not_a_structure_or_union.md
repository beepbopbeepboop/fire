# COMPILE_FAIL: Lib/socket.py — request for member '__module__' in something not a structure or union

## Status (updated 2026-08-06)

Re-ran with a 150s timeout: got partway through (produced the usual
`drop stale export` dylib-link noise, then an `os.py: 'relpath' is
ambiguous` transitive-compile-fallback note) then TIMED OUT with no
further output. Retried standalone in the background — still running
after 9+ minutes before being killed for this session's time budget
(on a machine also running several other agents' `mojo.py build`
processes concurrently).

`socket.py` has a large transitive import graph (imports `os`, `sys`,
`enum`, `errno`, `io`, `selectors`, ... each with their own further
imports), matching the profile of the ALREADY-DOCUMENTED performance
hard bug `bugs/hard/PERF_nested_module_compile_walk_ast_quadratic_rescan.md`
(confirmed via a `_walk_ast`-call-count blowup on a similarly-shaped
file, `Lib/contextlib.py` — see `bugs/COMPILE_FAIL_Lib_contextlib_
request_for_member_module_in_something_not_a_structure_or_union.md`,
also timing out this session for the identical reason). Not
independently profiled here (would need `cProfile` + a longer budget
than this session had left), but the symptom match (times out only for
transitive-import-heavy files, produces no output for a very long
stretch) is strong. Not investigated further — see that doc for the
concrete root cause and phased fix plan.

The ORIGINAL `__module__`/"consolidated" note below is STALE (from an
older bug-tracking scheme; the referenced `consolidated/` directory no
longer exists) — not re-verified since the file never finishes
compiling within any reasonable timeout now.

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

Source file: `/Users/mrs/net/Python-3.14.6/Lib/socket.py`
