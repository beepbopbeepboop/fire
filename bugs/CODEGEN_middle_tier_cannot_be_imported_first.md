# CODEGEN: `mojo/middle/*` cannot be imported first — a circular import that `gimple_codegen` happens to hide

## Status (2026-10-02 — measured on the merged bug-batch base `bc17a62b`, NOT fixed, and not this worker's claim)

Found while running `python3 test_suite.py` (the one test that covers
`tools/suite.py`'s registry, where a new job was being registered). It reports
295 passed, 2 failed, and this is the first of the two:

```
FAIL  imports: every real entry point imports first
  mojo.middle.calls_shared: ImportError: cannot import name
      'user_dunder_repr_call' from partially initialized module
      'mojo.middle.calls_shared' (most likely due to a circular import)
  mojo.middle.funcs_shared: ... '_SELFHOST_EXTRA_FIELD_CACHE' ...
  mojo.middle.infra_infer: ... '_FC_SEP' ...
  mojo.middle.loops_shared: ... '_gfl_declare_target_name' ...
  mojo.middle.methods_shared: ... '_is_selfhost_source_file' ...
  mojo.middle.module_shared: ... '_LIST_RETURNING_METHODS' ...
  mojo.middle.resolve_shared: ... '_calls_in_stmts' ...
  mojo.middle.stmts_shared: ... '_annotation_container_elem_type' ...
  mojo.backend_gimple.module_gen: ... '_FC_SEP' ...
```

Nine entry points, all of `mojo/middle/*` and the one that uses them all.
Not stale bytecode — reproduced with every `__pycache__` in the tree deleted.
Not this branch's change: the only diff to `mojo/` on this branch is nine
comment lines (`git diff <base>~1 -- mojo/` is a rename of `mojo dylib` to
`fire dylib` in prose), which cannot move a name across a module boundary.

## What it is

Every module of the middle tier opens with the same four lines:

```python
from mojo.middle.types import *          # 15
from mojo.middle.exprtypes import *      # 16
from mojo.middle.solvers import *        # 17
import gimple_codegen                    # 18   <-- constants
```

and `gimple_codegen` imports `mojo.backend_gimple.module_gen`, which does

```python
import mojo.middle.infra_infer as ginf   # module_gen.py:42
```

while some other module in the cycle does a NAME import from the middle tier:

```
from mojo.middle.infra_infer import _FC_SEP
```

So entering the tree through a middle-tier module runs
`infra_infer` → `gimple_codegen` → `module_gen` → `from mojo.middle.infra_infer
import _FC_SEP`, and `infra_infer` is still executing its own line 21, so the
`from` finds a half-built module. Entering through `gimple_codegen`,
`fire_compiler` or `myinterpreter` works, which is why nothing notices: every
real entry point in `driver.py` reaches `gimple_codegen` first, and
`test_suite.py` is the only thing in the tree that imports a module FIRST on
purpose.

The `import gimple_codegen` line is load-bearing per its own comment
("constants used by some extracted helpers"), so the fix is not to delete it.
The asymmetry is that `import X` (a module object, resolved lazily at attribute
access) survives a half-initialised `X`, and `from X import NAME` (resolved
EAGERLY at import time) does not.

## Why it matters

It is one attribute access away from being a hard failure at run time rather
than an import-order curiosity: every one of these nine modules is imported by
name from somewhere, and the day a script, a test, or a new entry point imports
one of them first it dies with an ImportError that names a circular dependency
nobody can see in the file that caused it. It is also, right now, a RED in a
gate: `suite-self-test` is `cache=True` and in `check`, so the first person to
run `make check` after this lands sees a failure whose two other candidate
causes (this doc, and
`bugs/TEST_estate_check_red_on_two_form3_test_files.md`, the estate half of the
same run) are different bugs.

## Exact next step

One change per site, in the owner of the middle tier: turn each
`from mojo.middle.X import NAME` that participates in the cycle into
`import mojo.middle.X as _X` plus qualified uses, which is what
`module_gen.py:42` already does for `infra_infer` and why `module_gen` itself
survives entering through `gimple_codegen`. The eight names to move are the ones
the failure messages quote; `grep -n 'from mojo\.middle\.[a-z_]* import' mojo/
gimple_codegen.py mojo/backend_gimple/*.py` lists the sites. Then re-run
`python3 test_suite.py` and the check goes green on its own — which is the
cheapest possible proof, since the check is the measurement.

**Not attempted by the worker that filed this**: the files are
`mojo/middle/*` and `mojo/backend_gimple/*`, which are other claims' write
sets, and every one of them is being edited in parallel; a rename across eight
modules under merge pressure is the integrator's cost, not this doc's author's.