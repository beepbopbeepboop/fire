# FORMAL_bindings_mojo_build_never_terminates: `std/python/bindings.mojo` wedges the arm64 formal build, and only the sweep's `-t 30` is stopping it

**Status: found and MEASURED, not fixed.** It is a hang, not a slow build and
not a memory blow-up, and the sweep's per-file timeout is currently the only
thing bounding it. Found from the arm64 sweep of 2026-10-01
(`bugs/FORMAL_sweep_work_map_2026-10-01.md` §5).

## What is wrong

```
TOOL: ../new-modular/Mojo/stdlib/std/python/bindings.mojo  (timeout (> 30s))
```

A timeout is a fact about the machine's load, not about the source, and this one
is neither. Measured with the timeout removed:

```
$ python3 .tmp/trace_one.py …/new-modular/Mojo/stdlib/std/python/bindings.mojo 850
  t=  0.0  rss=0.01 GB  procs=1
  t=  0.3  rss=0.04 GB  procs=1
  t=  0.6  rss=0.05 GB  procs=1
  t=  0.8  rss=0.05 GB  procs=1
  t=  1.1  rss=0.06 GB  procs=1
  t=  1.6  rss=0.06 GB  procs=1
  OVER BUDGET
bindings.mojo rc=None secs=850.1 PEAK=0.06 GB
```

**850 seconds, still running, at a flat 0.06 GB and no growth.** So:

* not memory (0.06 GB, and no growth in 850 s);
* not a deep recursion in the allocator (RSS is flat, so it is not
  accumulating);
* **a loop.** CPU-bound non-progress, which is what makes it worth a bug rather
  than a `-t` note: it is the one input in the default 623-file sweep that
  cannot be swept at all, and the sweep reports it as a property of the machine
  (`tool`, "a too-small -t is the usual cause") when it is a property of the
  file.

It is also the reason the sweep's `-t` matters more than it looks. `-t` is the
only bound on it, and the sweep's per-file timeout is a `subprocess.run(timeout=)`
that SIGKILLs the direct child — which is enough here only because
`fire.py build --formal` on this file spawns nothing (measured: 0 orphan
`fire.py` processes after a killed run). **A file that both loops and spawns
would leak its children**, because the timeout is not a tree kill. That is a
second, smaller defect and it is listed at the end.

## Smallest reproducer

```sh
python3 fire.py build --formal --no-prove --backend=arm64 -o /tmp/b.macho \
  /Users/mrs/net/chatgpt/claude/new-modular/Mojo/stdlib/std/python/bindings.mojo
# does not terminate; 0.06 GB, flat
```

Same file, same wedge, on x86-64 (it is in the owner's x86-64 log as
`TOOL: … (timeout (> 30s))` too), so this is not an arm64 backend problem.

## What to look at, in order

1. **Is it the sweep, or the build?** `tools/formal_sweep.py` passes
   `--no-prove`, so `formal/arm64_proof_gen.py` and `lean` are out. It is
   `formal/build.py` + `formal/arm64_codegen.py` on this one file.
2. **Where it is.** Run the reproducer under a sampling profiler — `py-spy dump
   --pid` if it is installed, or a SIGQUIT/`sys.settrace` equivalent — to get
   the stack it is in after a few seconds. That single fact decides everything
   else, and it is cheap.
3. **The import closure.** `bindings.mojo` is 70,924 bytes, one of the larger
   new-modular stdlib files, and the formal backend builds a dylib for every
   module in its eager import closure (`formal/imports.py`'s
   `build_module_dylib`), recursing. A cycle there is broken by `_stack`, so a
   hang is more likely in the *walk* than in the recursion — but that is a
   guess, and step 2 answers it.
4. **The 2026-10-01 sweep's own evidence:** it is the only one of 623 files in
   this class, and it is `codegen/dependency`-shaped (its module exports are
   reached through `std/python/`), so whatever the loop is, it is specific to
   this closure.

## The second, smaller defect, in the same measurement

`tools/formal_sweep.py`'s per-file timeout is
`subprocess.run(..., timeout=…)`, which SIGKILLs the process it started and
nothing below it. With the new per-file memory ceiling that asymmetry is now
half-fixed — the ceiling goes through `tools/memcap.py`, which walks and kills
the whole tree — but the TIMEOUT still does not. A file that loops *and*
spawns a compiler of its own would leave that compiler running after the sweep
moved on.

**Fix:** the timeout should take the tree down the same way the ceiling does.
`tools/procrun.py` already has exactly this — `procrun.spawn()` takes
`start_new_session=True` and calls `procrun.kill_group(p)` on timeout, and
`tools/suite.py` uses it for every job it runs. `formal_sweep.py` should use
`procrun.spawn` rather than `subprocess.run`, which also removes the second
process-walk copy rather than adding a third. Not done here because
`formal_sweep.py`'s per-file build needs `stdout` and `stderr` SEPARATE (the
classifier prefers stderr), and `procrun.spawn` merges them; that needs
deciding, and the decision belongs with whoever owns the sweep's cache key.
