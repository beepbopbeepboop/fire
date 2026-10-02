# The formal CAS verdict key does not include the `formal/hostmods/*.mojo` a build actually compiles

**Area:** FORMAL (the sweep's verdict cache). Found 2026-10-01 on
`work/formal-re-refusal` while measuring the `re.mojo` fix, and it is a
measurement bug rather than a codegen one: it reports a stale verdict as a
current one, which is the one thing a sweep must never do.

## What was run

`tools/formal_sweep.py` over four files that import `re`, on x86-64, twelve
minutes apart, with `formal/hostmods/re.mojo` changed in between (its widest
signature went from seven parameters to six, so the module — and with it every
one of those four files — began to build):

    $ python3 tools/formal_sweep.py --arch x86_64 -j 4 -t 120 \
          tools/mem_slope.py tools/gatewatch.py module_spec_gen.py \
          test_cli_usage_text.py
    CODEGEN/DEPENDENCY: module_spec_gen.py  (build: module_spec_gen.py imports
      're', which cannot be built either: re.mojo: sub: 7 parameters exceeds
      the 6 the formal x86-64 ABI passes in registers)
    … 4 of 4, identical
    cas: 4 hit / 0 miss / 0 not cached (4 files)
    verdict history: previous report … unchanged: 4

`cas: 4 hit` is the finding: nothing was rebuilt, so the second run answered
from the store the verdict the first run wrote. The build it is standing in for
now succeeds — `fire.py build --formal --no-prove --backend=x86_64` on each of
the four is exit 0, and with a fresh `GMOJO_HOME` the same sweep reports them
`NOT-ANSWERABLE/HOST-IMPORT` on `subprocess` / `resource`, i.e. off the codegen
denominator entirely.

    $ GMOJO_HOME=$PWD/.tmp/fresh-cas python3 tools/formal_sweep.py … --arch x86_64 …
    cas: 0 hit / 4 miss / 0 not cached (4 files)

## Why the key cannot see the change

`cas.formal_build_key(source, path, flags, criteria)` folds in `ABI_VERSION`,
`formal_fingerprint()`, the toolchain, the source bytes and the sweep tool's own
source. `formal_fingerprint()` is `_FORMAL_SOURCES` hashed: `fire.py`,
`fire_compiler.py`, every `formal/**/*.py` and every `mojo/middle/*.py`
(`cas.py:437-446`). It is a `.py` glob, and every module this backend COMPILES
AS SOURCE — `formal/hostmods/re.mojo`, `hashlib.mojo`, `struct.mojo`, `os/**`,
`argparse.mojo` — is a `.mojo` file. So editing one of them cannot move the
key, for any build that reaches it.

The docstring says why, and the reason was true when it was written:

> * "imported signatures" do not exist here — compile_formal compiles one file
>   and skips its import statements, so a stdlib edit cannot change this
>   artifact and stdlib_fingerprint() is deliberately not folded in.

`compile_formal` does skip import statements, but it does not skip the imports:
`formal/build.py:_resolve_imports` compiles every module the file imports into
a module dylib and links it, and a failure there IS the verdict (that is the
whole `CODEGEN/DEPENDENCY` class). The premise the exclusion rests on — that
nothing outside the entry file reaches the artifact — stopped being true when
`formal/imports.py` stopped modelling `re` as a host module and started
compiling it.

Note the module DYLIB itself is not stale: `formal/imports.py`'s `_BUILT` is a
per-process cache keyed by `(arch, path)`, and each `fire.py build` is a new
process, so every build recompiles the module from the bytes on disk. Only the
sweep's stored VERDICT is stale, which is why the symptom is a sweep reporting
a fixed file as still broken rather than a program linking an old library.

## What this costs, and who it hits

The `tools/formal_sweep.py` run the gate and the sweep work map are read from.
A fix to any `formal/hostmods/*.mojo` is invisible to it until something else
in `_FORMAL_SOURCES` changes, so:

  * `verdict history: unchanged: N` is reported for a fix that moved N files;
  * the head-to-head "before / after" tables in
    `bugs/FORMAL_sweep_work_map_*.md` compare two runs where one of them never
    ran the build;
  * and the failure mode is silent in the direction that matters — a sweep run
    right after a fix says the fix did nothing.

Every `re`-row and `hashlib`-row measurement in this repo's docs needs a fresh
`GMOJO_HOME` to be true, and nothing in the tool says so. (The 45-file
measurement on `work/formal-re-refusal` was taken that way, with
`GMOJO_HOME=$PWD/.tmp/fresh-cas`.)

## The next step

Fold the host-module sources into the key. The narrow version is one line —
add `formal/hostmods/**/*.mojo` to `_FORMAL_SOURCES` — and it is right for
every build, because `formal/build.py` can only ever reach the modules in that
directory (`formal/imports.py`'s resolver looks there for a stdlib name). It
over-invalidates: a `sys.mojo` edit would invalidate a verdict for a file that
imports only `re`, which costs a rebuild and nothing else.

The exact version keys on the file's own RESOLVED IMPORT CLOSURE, which is what
`formal/imports.py:imported_modules` already computes, and invalidates a verdict
only when a module that file actually imports changed. That is the same shape
as `stdlib_fingerprint()` being deliberately left out, done deliberately
instead: the argument against folding module content in was that no module
content reaches the artifact, and that argument is what has to go.

Whichever is chosen, the docstring's third bullet is what has to change: it is
the sentence that will be read next time somebody wonders whether an import
should be in the key, and it is currently wrong.