# `build_mojo_cli.py` is dead code that the self-host cache key still depends on

**Area:** tools / build cache. **Status:** open, not started. Found 2026-09-29
while fixing the `runner` job's dead `build/mojo` guard (the sibling of this is
fixed on `work/runner-stale-mojo`; this one is in a file that branch does not
touch).

## What it is

`build_mojo_cli.py` is a generator. `create_mojo_cli()` writes a ~440-line
Python CLI script to `build/mojo` and chmods it +x:

```python
def create_mojo_cli():
    """Create the mojo CLI script in build/mojo"""
    mojo_path = os.path.join(BUILD_DIR, 'mojo')
```

So `build/mojo` — the file `test_runner.py` used to preflight on — has **two**
producers in this tree, and this is the other one. It is not the Makefile's
`build/fire` link rule (renamed in 563ec43); it is a separate script generator
that the mojo->fire rename never reached, which is why its docstring, its output
path, and its `MOJO_CLI_SCRIPT` banner all still say `mojo`.

## What I ran, and what I saw

```
$ rg -n "build_mojo_cli" --glob '!build/**' --glob '!doc/**' --glob '!bugs/**' .
gimple_codegen.py:4909:    closure digest — so every caller (--dump, build_executable, build_mojo_cli,
cas.py:188:    'build_mojo_cli.py',
REF.html:146:  ... fire.py, driver.py, build_mojo_cli.py, build_module.py, ...

$ rg -n "^import|^from" fire.py fire_main.py
  # no import of build_mojo_cli anywhere
```

Three hits, and none of them is a caller:

- `gimple_codegen.py:4909` is the word appearing inside a *comment* about the
  closure digest.
- `REF.html:146` is a documentation table.
- `cas.py:188` is the problem.

Nothing imports it, no Makefile rule runs it, and `fire.py` — the actual CLI
entry point — does not mention it. `python3 build_mojo_cli.py` still "works"
(it writes a file), which is exactly why this has stayed invisible: nothing
fails, nothing calls it, and the file it writes is gitignored.

## Why it is not harmless: it is in the self-host cache key

`cas.py:188` lists it in `_SELFHOST_EXTRA`, so it is part of
`selfhost_inputs()` and therefore of `selfhost_fingerprint()` — the input set
for the `mojoc` binary, for `stage2/mojo`, and for the whole-closure
`--dump-full` dumps. That list is the one CLAUDE.md calls the *only* sound key
for anything that compiles the compiler (the narrower `compiler_fingerprint()`
is explicitly UNSOUND for that purpose).

`selfhost_closure_is_complete()` — the check that is supposed to keep that list
honest — is one-directional by design. It reports files the import walk
*reaches* that the list does not hash (`missing`). It never reports files the
list hashes that nothing reaches. So an over-wide entry is permanently
invisible, and `test_suite.py:376` (which runs that check) is green.

The cost is the direction cas.py's own comment calls acceptable — "a build
cache that is too wide is wrong and a build cache that is too wide only costs a
rebuild". But it is more than a rebuild here: it is a *live dependency* on a
file that is one `git rm` away from being unbuildable, sitting in the key for
the binary whose entire purpose is to be trusted across a self-host chain. And
it is the second of the two producers of the exact artifact whose stale copy
made `test_runner.py` green by accident in the main checkout.

## Expected

Either:

1. `build_mojo_cli.py` is deleted (it is dead — the CLI is `fire.py`, and
   `fire.py build` is what every other path uses), **and** removed from
   `cas.py`'s `_SELFHOST_EXTRA` in the same commit; or
2. it is kept deliberately, in which case it needs a stated caller and its
   output path needs to be reconciled with the `build/fire` rule, so two
   generators do not both claim to produce "the CLI".

Either way `_SELFHOST_EXTRA` should stop carrying a file with no callers.

## Exact next step

Confirm (1) is safe, then land it as one commit:

```
git rm build_mojo_cli.py
# and drop the 'build_mojo_cli.py', line from cas.py's _SELFHOST_EXTRA
```

`gimple_codegen.py:4909`'s comment mentions it by name and should be updated in
the same commit — it is a comment, so it changes no behaviour, but leaving it
naming a deleted file is how the next reader concludes the file still exists.

Then re-run `python3 test_suite.py` (`suite-self-test`, which owns the
`selfhost_closure_is_complete` check) and `python3 tools/suite.py --list` to
confirm the fingerprint still covers the real closure.

**Why this is not in the same commit as the `test_runner.py` fix:** the
fingerprint feeds the artifact cache for `mojoc` and `stage2/mojo`, so
changing it is a compiled-path change that owes a full `make gate` — a
different cost class from a test that no longer reads a stale binary. CLAUDE.md
is explicit that a change passing only the interpreter suites is not evidence
the compiled path is unaffected.

## Also worth folding in

`cas.py` has no check in the *other* direction, and adding one is cheap and
would have caught this: assert that every entry of `_SELFHOST_EXTRA` is either
in `_COMPILER_SOURCES` or actually reached by
`selfhost_closure_is_complete()`'s import walk. That converts "invisible until
someone greps for it" into a green check that goes red when a hashed file stops
being real. It belongs with this fix, not before it — the over-wide list is not
a bug until something is deleted from it.
