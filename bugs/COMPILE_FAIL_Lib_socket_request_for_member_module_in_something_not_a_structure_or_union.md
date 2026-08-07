# COMPILE_FAIL: Lib/socket.py — request for member '__module__' in something not a structure or union

## Status (updated 2026-08-07, final): PERF timeout resolved, matmul crash fixed, but file still not PASS — multiple simultaneous blockers, confirmed via direct rebuild

The PERF hard bug this doc previously matched
(`bugs/hard/PERF_nested_module_compile_walk_ast_quadratic_rescan.md`)
has since had its Phase 2 fix land — `Lib/socket.py` no longer times
out: it now completes (via `mojo.py build`'s `build_executable`
fallback path) in ~61s, generating ~10 MB of C, and reaches a real GCC
error stage.

Also fixed this session: the first blocking error that used to appear
(`Lib/operator.py:118:9: error: implicit declaration of function
'int64_t___matmul__'`, from `def matmul(a, b): return a @ b`'s
untyped-param fallback) — `_lower_matmul`'s blind
`{struct_name}___matmul__` call for a non-struct operand type. Fixed by
a guarded weak stub, mirroring an existing pattern used for
unresolved-base-class method calls — verified against the full 5-step
gate, no full-corpus regression.

**Still not PASS — confirmed via a direct rebuild in the final merged
state: 669 total `error:` lines**, from (at least) two independent,
simultaneous blockers:

1. **338 of 669 (~50%)** are `'X' undeclared here ... did you mean
   'argparse_X'/'ast_X'/...'` — this is
   `bugs/hard/CODEGEN_same_bare_name_struct_collision_across_modules.md`
   (task #141), explicitly excluded from this session's scope (already
   assessed as feature-sized/high-risk, not to be re-attempted without
   new information). Not investigated further here — see that doc for
   the mechanism.
2. The remaining ~330 errors are several OTHER, unrelated,
   pre-existing bugs in the transitive closure, none blocked by task
   #141: `Lib/operator.py:270`'s `non-trivial conversion in 'var_decl'`,
   `Lib/operator.py:342`'s `expected expression before 'partial'`,
   `Lib/stat.py:179`'s `invalid operands to binary &` (int64_t vs
   char*), `Lib/posixpath.py`'s `expandvars_repl_env` struct-shape
   mismatch (`redefinition of...`/`'...' has no member named...`),
   `Lib/tokenize.py:390`'s `conflicting types for 'perror'`. None of
   these investigated further here — each is its own separate,
   independent bug, and fixing #141 alone would NOT get this file to
   PASS on its own.

(`socket.py` was NOT re-tested against link mode/`driver.
compile_program`, which might fare differently since it doesn't inline
the whole transitive closure into one translation unit the way
`build_executable`'s fallback does — left for a future session.)

## Original status (2026-08-06, superseded above)

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
