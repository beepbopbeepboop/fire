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

- `bugs/FORMAL_examples_harness_exits_zero_on_all_skip.md`: the all-SKIP run
  exiting 0 is what made this look green for so long.
