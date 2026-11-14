# DIAGNOSTICS mojoc imports, part 2 — part 1: precompiled signature artifact

Part 1 of 3 of `bugs/hard/DIAGNOSTICS_mojoc_imports-part2.md` (which is part 2
of the umbrella `bugs/hard/DIAGNOSTICS_mojoc_imports.md`). Parts 2 and 3 of
this split are `DIAGNOSTICS_mojoc_imports-part2-part2.md` and
`DIAGNOSTICS_mojoc_imports-part2-part3.md`.

## Class
mid. Foundation work with no user-visible diagnostic of its own, but it is
bounded: one command, one artifact format, one reader.

## Current state (measured 2026-11-13)

The modular test this part serves is
`modular/mojo/test/mojo-tool/run/import_mojoc_implicit_default_param.mojo`
(it is not in this repo). Its RUN lines are:

    mojo precompile %t.dir/src/pkg -o %t.dir/deps/pkg.mojoc
    rm -rf %t.dir/src
    not mojo build -I %t.dir/deps %s -o %t.dir/main 2>&1 | FileCheck %s

and it expects the synthetic signature line
`struct Container[T: Marked, W: Wrapper = __init__(Int(4))]`.

In this repo there is **no** precompile step and **no** `.mojoc` format:

- `git grep -n precompile -- '*.py'` finds only a comment in `fire_compiler.py`.
- `git grep '\.mojoc'` finds only bug docs and the plan doc. The string
  `mojoc` in the tree names the self-host compiler binary, not a module format.
- So the "(if present)" hedge in `docs/diagnostics-missing-validation-plan.md`
  §10 is literal: there is nothing to load yet.

## Goal

Add the smallest real precompile-to-import path that carries a struct's
signature, including each parameter's default as source text, from a package
into an artifact that an importer can read after the package sources are
deleted.

1. `mojo precompile <pkg-dir> -o <out>.mojoc` (or the fire.py equivalent the
   tree already uses for CLI subcommands; check `fire.py`'s argument parsing
   first and reuse it, do not add a second entry point) parses every module in
   the package, and writes one JSON artifact per package containing, for each
   top-level struct and function: name, bracket params (name, trait/type
   text, default source text or null), runtime params with the same fields.
2. Import side: a `-I <dir>` root that contains `*.mojoc` files resolves
   `from pkg import X` to the artifact when no `pkg/` source directory exists.
   The reader returns the same signature records the source path produces, so
   downstream checks do not branch on where a signature came from.
3. Keep the artifact format in one module (for example
   `mojo/middle/mojoc_artifact.py`) with one reader and one writer. Do not
   duplicate the source-side signature extraction; call the existing one.

## Acceptance

After `precompile` on a fixture package and deletion of its sources, importing
`Container` through `-I <dir>` yields a signature record whose bracket param `W`
has trait text `Wrapper` and default source text `__init__(Int(4))`, and whose
`T` is `Marked`. No diagnostic is emitted by this part itself.

## Done when

File: `test_mojoc_precompile_signature.py` (repo root; created by this part,
modelled on `test_align_decorator_literal_diagnostic.py`). It builds the fixture
package under `.tmp/`, precompiles it, deletes the sources, and asserts the
record above.

Command: `python3 test_mojoc_precompile_signature.py`

Note for the worker: this test parses and reads only. It must not compile
anything, so it needs no memslot wrapper.

## Status

- **Open.** Nothing landed yet. Parts 2 and 3 depend on this record shape.
