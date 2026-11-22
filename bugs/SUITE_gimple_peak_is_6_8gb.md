# SUITE: the `gimple` job's peak is 6.5-6.8 GB, not the 0.4 GB its class is sized from

**Job:** `gimple` (`python3 test_gimple.py`), registered in `tools/suite.py` as
`test('gimple', ..., cache=True, mem='tiny', ...)` — `tiny` is a 4 GB ceiling.

Measured 2026-11-21 while landing stage 5b step 4 (`WordFacts` one record per
temp); the measurement is **pre-existing**, not caused by that change (see
"Discriminator" below).

## What I ran and what I saw

```
$ PYTHONUNBUFFERED=1 python3 tools/memslot.py --gb 4 --label gimple -- python3 test_gimple.py
...
PASS  signed64_integer_literal_boundaries        <- last test that finished
memcap: BREACH  4.2 GB > 4.0 GB ceiling (104%), 1 procs -- killing gimple
memcap: this is a RESOURCE failure, not a verdict on the thing under test
```

The same file at an 8 GB ceiling finishes green (`Results: 472 passed, 0
failed`) and reports `peak 6.2 GB`. So the file needs ~6.2-6.8 GB and the
registered class is 4 GB: `python3 tools/suite.py gimple` (and therefore
`make check`, which contains it) kills it as RESOURCE on this machine with the
default ceilings.

`python3 tools/suite.py --list` says, for this job:

```
gimple   cmd  mem=tiny=4GB peak=0.4GB cached [check,gate]
```

**The 0.4 GB is where the class came from, and it is wrong by 17x.**

## The single compile that costs it

The test after `signed64_integer_literal_boundaries` is
`test_known_function_not_shadowed_by_global_fnptr`, which does

```python
c_src = compile_to_gimple(src, do_imports=True,
                          filename=os.path.join(_PROJECT_DIR, "fire.py"))
```

for a 4-line snippet (`import cas` + one function calling `cas._hash`).
Reproduced alone, from the tree root, under `--gb 8`:

```
$ python3 -c '<that compile only>'
C bytes: 123263960            # 123 MB of generated C
memcap: done, peak 6.5 GB across up to 1 procs (ceiling 8.0 GB), child exit 0
```

So it is one `do_imports=True` compile, not the 472 tests' accumulated state:
the generated C for that closure is 123 MB and building it costs 6.5 GB.

## Discriminator (why this is not the stage 5b landing)

The same probe on a scratch worktree of `master dd5da5eb5` (2026-11-21):

```
C bytes: 136823819
memcap: done, peak 6.8 GB across up to 1 procs (ceiling 8.0 GB), child exit 0
```

master is *larger* than the branch (136 MB / 6.8 GB vs 123 MB / 6.5 GB, the
record's fewer statements), so the landing does not introduce this and does
not make it worse.

## Expected

A registered job's class covers 1.5x its measured peak and the peak is a
measurement (`MEASURED_PEAK_GB` / `--apply-peaks`), per
`doc/POLICY_memory_over_4gb.md`. Either the job's real peak is in the table
and the class follows it (`small`, 8 GB, with a `memwhy`), or the compile
stops costing 6.5 GB.

## Next step (in order)

1. **Re-measure and re-class, so the everyday loop stops being red.** Add
   `'gimple': (6.8, 'measured')` to `MEASURED_PEAK_GB` in `tools/suite.py`
   and change the registration's `mem='tiny'` to `mem='small'` with a
   `memwhy` naming this doc and the 6.8 GB reading. Then
   `python3 tools/suite.py --no-cache gimple` and confirm green.
   This is the mitigation; it does not fix the C size below.
2. **Find why the closure dump for `import cas` is 123 MB.** `cas` is a
   small module; 123 MB of C from it means something is being emitted many
   times over (the same shape as the 2026-11-18 extern/duplicate-module
   class of bug in `test_gimple.py`'s neighbouring comment, and as
   `CODEGEN_ab_native_fails`'s "silently dropped two compiled sibling
   modules" inverse). Measure per module in the dump:
   `grep -c "^/\* .*\.mojo\?py \*/"`-style counts of the `#line` directives,
   or count `^mojo_.*__` definitions per source file, and compare with the
   module count the closure should have. A `--dump-full` of the closure is
   the same artifact and is already known to cost 12-15 GB
   (`CODEGEN_bootstrap_resource_blowup`), so this is very likely that same
   duplication, not a new mechanism.
3. If step 2 lands, re-measure and lower the class back down in the same
   commit (the class is a claim on the machine; 8 GB reserved for a 0.4 GB
   job is 8 other jobs that cannot run).

Delete this doc when the job is green at its default ceiling with the
measured peak recorded.
