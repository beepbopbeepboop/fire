# FORMAL_the_runtime_dylib_leaves_its_staging_directory: 520 kB per cold CAS, never removed

**Measured 2026-10-05 on `work/formal38-reproducible-builds`, on the
reproducibility sweep.** Found next door, not caused by it, and filed rather
than fixed because `build_stdlib_dylib.py` is nobody's claim and the fix is a
`finally` in a file eight formal workers are not all avoiding.

## What was measured

```
$ T=$(mktemp -d); H=$(mktemp -d)
$ GMOJO_HOME=$H TMPDIR=$T python3 fire.py build --formal --no-prove \
      -o mp.aout -n 10 mp.mojo          # mp.mojo calls mojo_print("hi")
$ du -sh $T/mojo_rt_*
520K    …/mojo_rt_bra97_71
```

The directory holds `_mojo_reflect.c`, `_mojo_reflect.o` and eight runtime
objects (`fire_runtime.o`, `fire_coro.o`, `fire_coro_gen.o`,
`fire_coro_ctx_generic.o`, `fire_async_runtime.o`, `fire_async_sched.o`), and
after the build it is still there. `runtime_dylib`
(`build_stdlib_dylib.py:1386`) does

```python
wd = tempfile.mkdtemp(prefix='mojo_rt_')
…
staged = os.path.join(wd, name)
subprocess.run(_dylink(cc, staged, objs, …), check=True)
_arch_or_die(staged, arch, 'linked runtime dylib')
os.replace(staged, out)
return out
```

`os.replace` moves the **dylib** out; the eight objects and the generated C stay
behind, and nothing removes `wd`. There is no `atexit`, no `try/finally`, and no
`shutil.rmtree` anywhere in the function.

## Why it is worth a document and not a shrug

The cost is per **cold CAS**, not per build — the cache hit at the top of the
function returns before `mkdtemp` — so the shape of the damage is set by who
uses per-test CAS homes, and this tree has a lot of them:
`test_formal_imports.py`, `test_formal_sys.py`, `test_formal_argparse.py`,
`test_formal_trait_module.py`, `test_formal_module_attr.py`,
`test_formal_cross_module.py` and `test_formal_monomorph.py` all set
`GMOJO_HOME` to a fresh `mkdtemp`. One such test that happens to build an image
calling a `mojo_*` name leaks half a megabyte. Measured on this worktree's own
`.tmp` during the reproducibility sweep: **34 leaked directories, ~500 kB each,
~17 MB**, all from the sweep's 312-case corpus run (which builds into a
per-case CAS), in about twelve minutes.

The shared `~/.gmojo/cas/rtdylib` is a second, separate growth: 1.16 GB of
`libmojostdlib.<arch>.<digest>.dylib` plus manifests, one per distinct
`compiler_fingerprint()`. That one is a cache doing what a cache does — it has
no eviction, which is worth knowing and is not this bug.

## The fix

Three lines, in the same function:

```python
wd = tempfile.mkdtemp(prefix='mojo_rt_')
try:
    …everything through os.replace(staged, out)…
    return out
finally:
    shutil.rmtree(wd, ignore_errors=True)
```

`ignore_errors=True` because the failure mode that matters is the build's, not
the cleanup's: a stale directory in `$TMPDIR` is worth less than a
`FormalBuildError` about it. `formal/build.py::_publish_signed_image` is the
model to copy — it stages, publishes, and removes its staging **directory** in a
`finally` with the same reasoning written down, and it is the reason a killed
build leaves no debris for a later glob to mistake for a library.

Nothing may read `wd` after the `finally`, and nothing does: `os.replace` has
already moved the one artifact that leaves it.

## Not reproducible-builds, but found by it

Worth saying plainly: this is a resource leak, not a reproducibility defect,
and the sweep found it because a reproducibility sweep builds the same thing
several hundred times under fresh caches. It is filed here rather than fixed
because the change belongs to whoever owns `build_stdlib_dylib.py`.
