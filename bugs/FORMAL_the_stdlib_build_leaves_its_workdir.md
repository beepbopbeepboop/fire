# FORMAL_the_stdlib_build_leaves_its_workdir: `build()`'s `mojostdlib_*` work directory is never removed

**Status: NOT FIXED — filed 2026-10-07 by `work/formal119-docs` while fixing the
sibling leak `FORMAL_the_runtime_dylib_leaves_its_staging_directory.md` (which is
`runtime_dylib`'s `mojo_rt_*` directory, now removed in a `finally`).** This is
the third instance of the same shape in `build_stdlib_dylib.py` — `mkdtemp` +
`subprocess.run`s + no cleanup — and it is the largest of the three, so it is
written down rather than folded into that one-commit fix: `build()` is ~340
lines with the whole tail inside `with _OutputLock(out)`, and wrapping it in a
`try/finally` is a large re-indent that does not belong in a leak-fix commit.

## What was measured

`build()` (`build_stdlib_dylib.py:919`) does `workdir =
tempfile.mkdtemp(prefix='mojostdlib_')` at `:936` and never removes it: there is
no `shutil.rmtree`, no `atexit`, and no `TemporaryDirectory` anywhere in the
function. `build_stdlib()` (`:1581`) is a one-line delegation to it, so EVERY
full-stdlib dylib build leaks its work directory.

A one-module `build()` cold, with `shutil.rmtree` patched to a no-op so the
pre-fix state is observable:

```
$ GMOJO_HOME=$(mktemp -d)/cas TMPDIR=$(mktemp -d) python3 -c "
import shutil; shutil.rmtree = lambda *a, **k: None
from build_stdlib_dylib import build, stdlib_modules
m = [x for x in stdlib_modules() if x.endswith('floatable.mojo')][0]
build([m], 'tmp/x.dylib', use_cache=False, link_runtime=False, jobs=1,
      track_local_deps=False, arch='arm64')"
left dirs: ['mojostdlib_pnf8qu75']  bytes 324327
files: std_builtin_floatable.c/.o, _mojo_reflect.c/.o, fire_runtime.o,
       fire_coro.o, fire_coro_gen.o, fire_coro_ctx_aarch64.o,
       fire_async_runtime.o, fire_async_sched.o
```

324 kB for ONE module. A full stdlib build is 664 modules plus the runtime and
the reflection table, so the directory is tens to hundreds of MB per build, and
it is per **cold CAS**: a cached `build()` still runs the pre-pass and the
`with _OutputLock` tail but the objects come from `cas.get_or_build`, so the
work directory can be smaller — it is created unconditionally at `:936`
regardless.

## The fix, and why it is not three lines here

The same `try/finally` shape as `runtime_dylib`:

```python
    workdir = tempfile.mkdtemp(prefix='mojostdlib_')
    try:
        ...everything through the `return out` inside `with _OutputLock`...
        return out
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
```

The complication is only that the body is long and the `return` is nested inside
`with _OutputLock(out) as _lock_fd:` — a `finally` on an outer `try` still runs
on the `with`'s exit and on every `raise`, so the shape is correct; it is the
re-indent of ~320 lines that makes it a commit of its own. A `with
_staging_dir('mojostdlib_') as workdir:` context manager (alongside the ones
used by `runtime_dylib` and `_driver_targets`, which are now `try/finally`) would
consolidate all three and is the shape to prefer if someone is already touching
this file.

## Next step

Add the `finally` (or the context manager) around `build()`'s body, and pin it by
extending `test_formal_runtime_link.py`'s
`test_a_cold_runtime_build_leaves_no_staging_directory` to assert
`mojostdlib_*` is absent after a one-module `build()` — the same cold-subprocess
setup it already uses.
