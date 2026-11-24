# Self-host: the closure dump has 4 NEW weak stubs on master (found 2026-11-23)

`python3 tools/c_oracle.py check --base ba5afb8d4 --closure` on master (2026-11-23) reports four
stubs that the self-hosted compiler cannot resolve. `ba5afb8d4` (2026-11-21) had none:

    PRESENCE_WORD          defined in mojo/middle/types.py, read from mojo/backend_gimple/module_gen.py
    _IDENT_CHARS           defined in mojo/middle/types.py
    _NONE_TYPE_MARKER      defined in mojo/middle/resolve_shared.py
    _WALK_AST_MAX_DEPTH    defined in mojo/middle/exprtypes.py

They are module-level CONSTANTS, read from another module (or through an import) in a way the
self-hosted compile does not resolve. It emits a weak "unavailable in compiled mode" stub that
returns 0. So the self-hosted compiler sees 0 where the reference sees the constant. `make
bootstrap` (`bootstrap-stage1-transitive`) fails on exactly this. Nothing else catches it: the corpus
hashes, the runner and stdlib-syntax all run the Python reference.

## Find the commit(s)

Bisect between `ba5afb8d4` (good) and master (bad). The test per step is the closure stub count, about
6 minutes:

    git bisect start master ba5afb8d4
    git bisect run sh -c 'python3 tools/c_oracle.py check --base ba5afb8d4 --closure -j 4 2>&1 | grep -q "NEW stub" && exit 1 || exit 0'

Use a scratch worktree, not the main checkout. The four names may come from different commits:
bisect on each name separately if the first answer explains only some of them.

## Fix

The working pattern is in `gimple_codegen.py`'s `_SELFHOST_SIGS`, and in how other cross-module
constants are read (`from <module> import NAME` at the reader's top, as `emit_funcs.py` does for
`_as_comptimevar_node`). Read how the reader spells each one: a `mod.NAME` attribute read is the
likely shape. Fix each so the closure dump has 0 new stubs.

## Done when

`python3 tools/c_oracle.py check --base ba5afb8d4 --closure` prints `no new stubs` for the closure (the
corpus C differences against that old base are expected and are not this bug). Delete this doc in the
same commit.
