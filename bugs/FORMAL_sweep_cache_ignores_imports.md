# FORMAL_sweep_cache_ignores_imports: a swept file's cached verdict survives an edit to a module it imports

**Status: OPEN. `cas.formal_build_key`'s stated premise — "the formal backend …
resolves no imports" — stopped being true when the import mechanism landed, and
nobody updated the key. Every verdict the sweep has cached for a file that
imports a module is now a verdict about the module's OLD contents.**

Found while writing `sys.mojo` (2026-09-29, the `module:sys` claim), at
`ca6e758`. Measured below, not inferred.

---

## What the key says, and why it is now false

`cas.py`, `formal_build_key`'s own docstring:

> * "compiler" is `formal_fingerprint()` (formal/**, the parser, mojo/middle);
> * "toolchain" is the Python interpreter that runs the in-process arm64
>   emitter, plus the flags …
> * **"imported signatures" do not exist here — `compile_formal` compiles one
>   file and skips its import statements, so a stdlib edit cannot change this
>   artifact and `stdlib_fingerprint()` is deliberately not folded in.**

Every clause of the third bullet is now false on this path. `formal/imports.py`
resolves imports, `formal/build.py`'s `_resolve_imports` compiles each imported
module into a dylib, and the dylib goes on the image's link line: the module's
source decides which symbols the image binds, whether it builds at all, and the
image's whole dependency set. `formal/imports.py`'s own module docstring says
what this replaced — an import that was *silently dropped* left the calls it
implies as `BL`s against symbols nothing defines.

`formal_fingerprint()` covers `formal/**`, the parser and `mojo/middle`. It does
not cover a module source, and there is no mechanism that could: a module lives
at whatever path the resolver found it at, which is per-file.

## Measured

```console
$ python3 tools/formal_sweep.py --no-stdlib t_argv.mojo
CODEGEN: t_argv.mojo  (build: main: 'sys' is imported from `sys`, …)
cas: 0 hit / 1 miss / 0 not cached (1 files)

$ printf '\n# touched\n' >> sys.mojo

$ python3 tools/formal_sweep.py --no-stdlib t_argv.mojo
CODEGEN: t_argv.mojo  (build: main: 'sys' is imported from `sys`, …)
cas: 1 hit / 0 miss / 0 not cached (1 files)      <-- SERVED FROM CACHE
```

`sys.mojo` changed and the verdict was replayed. Note what makes this sharp:
the run is not merely stale about a *pass/fail* — the sweep's whole output is a
classification derived from the build's message, and a different module can
produce a different class for the same file (`not-answerable/host-import` when
the module cannot be found, `codegen/dependency` when the module is found and
refuses a construct, `pass` when it builds).

The same hole is in the executable side, one layer down: `build_module_dylib`
computes the dylib's FILE NAME from the module's source digest, so a changed
module gets a new path and a new library — but the sweep never gets that far,
because it never rebuilds.

## Why it is not fixed here

The fix is in `cas.py` and `tools/formal_sweep.py`, both shared, and it changes
the key of **every** formal verdict ever cached — which invalidates the whole
formal CAS in one step. That is the right thing to do and it is the integrator's
gate to measure, not a worker's. It is also exactly the kind of change that the
other module claims (`os`, `struct`) will want, so it should be done once.

## The exact next step

1. `run_one` in `tools/formal_sweep.py` already has the file's `path` and the
   build driver already resolved the imports; have it compute the
   **transitive** module closure's digest and pass it as a new
   `cas.formal_build_key(..., imports=<digest>)` argument, so the key moves when
   any module in the closure moves. `formal.imports.resolve_module_path` plus
   the manifest's own `depends_on` list is enough — no new resolution logic is
   needed, only reading the list the build already writes
   (`_record_depends`).
2. A cheap, sound first cut that needs no closure walk at all: fold the
   **mtime and size of every file the import resolver can reach** into the key.
   Cheaper still, and honest: add a `_criteria_id()`-style constant derived from
   the resolved module sources, which the sweep already recomputes per run.
3. Whatever the mechanism, pin it: a test that builds a file importing a module,
   edits the module, re-runs, and requires a `cas: … 0 hit` line. `test_formal.py`
   or a new small file; it needs no build, only two `cas.formal_build_key` calls
   with the module digest differing.

Until then: **a sweep run over a tree where a module source changed is not
evidence about anything that imports it.** The 14 files the `sys` sweep listed
were re-measured from a cleared CAS for exactly this reason, and the numbers in
that commit's message are from a cold run.

## Second measured instance, 2026-09-30: a re-sweep that measured nothing, and looked like a result

Re-measuring the argparse cause's ceiling
(`bugs/FORMAL_sweep_work_map_2026-09-30_r2.md` §3.1) hit this and it is worth
recording in the shape it actually takes, because nothing in the output says
"stale":

```
$ python3 tools/formal_sweep.py -j 8 -t 60 <the 37 files argparse blocks>
[arm64] 37 files: PASS=1 not-pass=36
cas: 35 hit / 2 miss / 0 not cached (37 files)
```

The fix under measurement was two `-> int` annotations in
`formal/hostmods/argparse.mojo`, and **35 of the 37 verdicts were the previous
run's**, replayed. Only the module itself and one other were rebuilt. The
summary line, the class counts and the coverage rate were all *shaped exactly
like a real result* — `PASS=1` is the number the real measurement also
produced — so a reader comparing this against the cold run below would find two
runs that agree, which is the worst possible outcome for a stale cache.

The root cause is narrower than "imports are not in the key", and that is what
makes it easy to miss: `cas._FORMAL_SOURCES` globs `formal/**/*.py`, so
**`formal/hostmods/*.mojo` — Mojo source this backend compiles, the one place a
module edit lands in practice — is not in `formal_fingerprint()` at all.**

The cold run, which is the measurement:

```
$ … env GMOJO_HOME=$PWD/.tmp/gmojo_nc python3 tools/formal_sweep.py -j 4 -t 60 <the 37>
[arm64] 37 files: PASS=1 not-pass=36
  pass 1, codegen 2, not-answerable/host-import 34
cas: 1 hit / 36 miss
```

**There is no `--no-cache`.** The only way to force a cold store today is to
point `GMOJO_HOME` at an empty directory, which is what step 1 of the fix would
make unnecessary. Until then, *any* measurement of a fix that lands in a `.mojo`
file under `formal/` — which is most hostmod work and all of `formal/hostmods` —
must be run that way, and the CAS line of the log is the only place that shows
whether it was.
