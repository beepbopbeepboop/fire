# formal/build.py is not reentrant: concurrent builds in one process corrupt each other

## Symptom

`test_x86_64_examples.py` (gate job `x86-examples`) ran the 45 formal examples
on a `ThreadPoolExecutor`. Results depended on timing:

- `toplevel_const` failed on x86-64 with
  `'LIMIT' has no home: the register allocator collected no home for it`.
- `toplevel_accum` was SKIPped on arm64 with `'SCALE' has no home`, and in
  other runs with `'LIMIT' has no home`.
- Some runs were **93/93 SKIP**, every arm64 build refused with
  `the image would bind 2 symbol(s) that nothing provides: snprintf, strtod`,
  and the process still exited 0.

Run serially (`-j 1`), the same tree gives 91 PASS / 2 NO-ORACLE / 0 SKIP /
0 FAIL on every run.

## Root cause (measured)

Not a load problem. The process-global state in `formal/model.py` and
`formal/build.py` is shared by every build in the interpreter:

1. **libsystem handle sentinel.** `model._libsystem_handle()` sets
   `_LIBSYSTEM_HANDLE = False` as an "in progress" marker before it loads
   `libSystem`. A second thread that calls it during that window gets `False`,
   which `_is_libsystem` reads as "not a C library symbol". Its answer is
   memoised in `_LIBSYSTEM_MEMO` and never revisited. Probe evidence: a
   logged stack showed a nested call from another thread
   (`build.py:_audit_bound_symbols` → `model._is_libsystem` →
   `_libsystem_handle`) entering while the outer call held the sentinel. The
   fallback then drops `snprintf`/`strtod` from the set of provided symbols.
2. **Per-program tables leak across builds.** A build reads module-level
   constants and home tables that another build in the same process has
   written. `toplevel_accum` defines `LIMIT`, and `toplevel_const` in the same
   process then reports `'LIMIT' has no home`.

The harness is now process-per-build (`test_x86_64_examples.py`'s
`ProcessPoolExecutor`), which is the workaround. It does not fix the compiler.

## Expected

`compile_formal(...)` returns the same result whether it runs once, or
concurrently with other `compile_formal` calls in the same process. Either the
compiler's state is per-build, or every entry point that touches the shared
state is serialised behind one lock, and the choice is recorded.

## Status (2026-10-30)

- **The lock half landed.** `formal/build.py` serialises every in-process
  entry into the compiler behind one `_COMPILE_LOCK` wrapping
  `compile_formal` — the choice this doc asked to be recorded, per-build
  state being the production answer and the lock the smaller change. The
  `compile_formal_dylib` entry is not wrapped: the tools that call it
  directly build in their own process, and on the executable path it is
  nested inside `compile_formal` (through `build_module_dylib`), where the
  lock is already held. `test_formal_link_accounting.py` gained
  `test_concurrent_compile_formal_calls_agree_with_the_serial_answer`
  (two `compile_formal` calls in one process, one a module-constant program,
  must answer the serial bytes) and
  `test_libsystem_handle_racing_callers_read_the_settled_answer` (eight
  threads on a cold libsystem state, twenty-five rounds; measured, the
  pre-fix marker was read wrong once in twenty single rounds, so one round
  would not have been a guard). All checks green under memslot.
- **What remains: the sentinel half, blocked out-of-tree.** The fix to
  `model._libsystem_handle` (the in-flight `False` marker replaced by a
  double-checked load behind `model._LIBSYSTEM_LOAD_LOCK`, with a racing
  caller blocking on the lock rather than reading the marker) is drafted in
  the worktree copy of `formal/model.py` and was verified green here before
  an in-progress stash-pop conflict landed in the same file (the hunk in the
  `parameter_kinds_by_call_site` region, which does not overlap the sentinel
  region, so resolving it keeps the drafted fix). Until that conflict is
  resolved the file does not parse and the sentinel fix cannot be committed;
  the doc stays open for that half and for step 4 (the harness going back to
  a thread pool, once both halves are in — the process pool remains the
  correct design until then).

## Next steps

1. Enumerate the module-level mutable state reached by `compile_formal`: every
   `global`, every module-level `dict`/`set`/`list` that a build writes, and the
   `_LIBSYSTEM_*` pair in `formal/model.py`. A quick way is
   `grep -n "^_[A-Z_]* = \\|global " formal/model.py formal/build.py`.
2. Fix the sentinel first, as it is small and self-contained: keep the loaded
   handle and an "attempted" flag separate, and guard the load with a
   `threading.Lock`, so a racing caller waits rather than reads `False`.
   Add a test that calls `_is_libsystem('snprintf')` from 8 threads and
   requires `True` from every one.
3. For the per-build tables, decide between per-build state (pass a context
   object) and one lock around `compile_formal`. The lock is the smaller change;
   per-build state is the production answer. Record the decision here.
4. When the compiler is safe under threads, `test_x86_64_examples.py` can go
   back to a thread pool. Until then the process pool is the correct harness
   design, and the comment at its `ProcessPoolExecutor` says why.

## Related

- The all-SKIP run exiting 0 — what made this look green for so long — was
  resolved 2026-10-30 in `test_x86_64_examples.py` itself: the harness now
  fails the run when SKIP exceeds its stated bound (`MAX_SKIP`), so a run
  whose arm64 reference is unavailable for most examples can no longer pass
  the gate silently.
